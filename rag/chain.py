"""
Основная RAG-цепочка:
  1. Роутинг запроса → local / global / dense
  2. Векторный поиск в Qdrant → тексты чанков из Postgres
  3. Поиск по графу через RAGU (если нужен по маршруту)
  4. Сборка контекста → генерация ответа через Ollama
"""

import asyncio
import json as _json
import os
import re
from typing import AsyncGenerator, Optional

import asyncpg
import httpx

from embeddings.embed_and_index import NewsIndexer, Reranker
from embeddings.remote import embed_query as _remote_embed_query
from graph.search import global_search, local_search
from qdrant_client import QdrantClient
from embeddings.embed_and_index import COLLECTION

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:32b")
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://user:password@localhost:5432/mydb")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

TOP_K = 50   # сколько берём из Qdrant до reranker'а
TOP_N = 10   # сколько отдаём в контекст после reranker'а
SCORE_THRESHOLD = 0.5  # чанки ниже порога отбрасываются до генерации, нужно будет подкрутить на реальных данных.

SYSTEM_PROMPT = """\
Ты — аналитик, создающий новостные сводки на русском языке.
Правила:
- Используй ТОЛЬКО информацию из предоставленного контекста.
- Не придумывай факты, цифры, имена.
- Ссылайся на источники в формате [id] — число соответствует id тега <doc>.
- Если в контексте недостаточно данных, ответь: "Недостаточно данных в базе знаний."
- Пиши кратко, структурированно, по-русски.\
"""

# Маркеры для эвристического роутинга
_GLOBAL_MARKERS = ("тенденци", "обзор", "ситуаци", "в целом", "в общем", "тренд", "динамик")
_LOCAL_MARKERS = ("кто ", "кто,", "кого", "какой", "назов", "перечисл", "какие компани")


def _route(query: str) -> str:
    """Возвращает 'global', 'local' или 'dense'."""
    q = query.lower()
    if any(m in q for m in _GLOBAL_MARKERS) or len(query) > 100:
        return "global"
    # Собственное имя (заглавная буква не в начале предложения) или явный local-маркер
    if any(m in q for m in _LOCAL_MARKERS) or re.search(r'(?<=[а-яё\s])[А-ЯЁ][а-яё]{2,}', query):
        return "local"
    return "dense"


async def _fetch_chunks(chunk_ids: list[int]) -> list[dict]:
    if not chunk_ids:
        return []
    conn = await asyncpg.connect(POSTGRES_DSN)
    try:
        rows = await conn.fetch(
            """
            SELECT chunk_id,
                   chunk_text AS text,
                   payload->>'source' AS source,
                   payload->>'published_at' AS published_at
            FROM chunk
            WHERE chunk_id = ANY($1::bigint[])
            ORDER BY array_position($1::bigint[], chunk_id)
            """,
            chunk_ids,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def _assemble_context(chunks: list[dict], graph_ctx: Optional[str]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        date_str = str(c.get("published_at", ""))[:10]
        parts.append(
            f'<doc id="{i}" source="{c["source"]}" date="{date_str}">\n'
            f'{c["text"]}\n</doc>'
        )
    if graph_ctx:
        parts.append(f"\n<graph_context>\n{graph_ctx}\n</graph_context>")
    return "\n\n".join(parts)


def _verify_citations(answer: str, num_docs: int) -> list[int]:
    """Возвращает список невалидных id из ответа модели (галлюцинации)."""
    cited = {int(m) for m in re.findall(r'\[(\d+)]', answer)}
    return [c for c in cited if c < 1 or c > num_docs]


async def _generate(context: str, query: str) -> str:
    user_msg = f"Контекст:\n{context}\n\nЗапрос: {query}"
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "stream": False,
                    #"think": False,
                },
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
    except Exception:
        return f"[Ollama недоступен] Найдено {context.count('<doc')} релевантных фрагментов. Настройте OLLAMA_URL для генерации ответа."


async def _generate_stream(context: str, query: str) -> AsyncGenerator[str, None]:
    user_msg = f"Контекст:\n{context}\n\nЗапрос: {query}"
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = _json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
    except Exception:
        yield f"[Ollama недоступен] Найдено {context.count('<doc')} релевантных фрагментов."


class RAGChain:
    def __init__(self, qdrant_url: str = QDRANT_URL, api_key: Optional[str] = QDRANT_API_KEY):
        self._use_remote_embed = bool(OLLAMA_URL)
        if self._use_remote_embed:
            self._qdrant = QdrantClient(url=qdrant_url, api_key=api_key, timeout=120)
        else:
            self._indexer = NewsIndexer(qdrant_url=qdrant_url, api_key=api_key)
        self._reranker = Reranker()

    async def _search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        if self._use_remote_embed:
            vector = await _remote_embed_query(query)
            results = self._qdrant.query_points(collection_name=COLLECTION, query=vector, limit=top_k)
            return [(r.id, r.score) for r in results.points]
        return self._indexer.search(query, top_k=top_k)

    async def stream_answer(self, query: str, top_k: int = TOP_K) -> AsyncGenerator[str, None]:
        route = _route(query)
        results = await self._search(query, top_k=top_k)
        chunk_ids = [cid for cid, score in results if score >= SCORE_THRESHOLD]

        if not chunk_ids and route == "dense":
            yield "Недостаточно данных в базе знаний."
            return

        if route == "global":
            try:
                chunks, graph_ctx = await asyncio.gather(
                    _fetch_chunks(chunk_ids), global_search(query)
                )
            except Exception:
                chunks = await _fetch_chunks(chunk_ids)
                graph_ctx = None
        elif route == "local":
            try:
                chunks, graph_ctx = await asyncio.gather(
                    _fetch_chunks(chunk_ids), local_search(query)
                )
            except Exception:
                chunks = await _fetch_chunks(chunk_ids)
                graph_ctx = None
        else:
            chunks = await _fetch_chunks(chunk_ids)
            graph_ctx = None

        if not chunks and not graph_ctx:
            yield "Недостаточно данных в базе знаний."
            return

        chunks = self._reranker.rerank(query, chunks, top_n=TOP_N)
        context = _assemble_context(chunks, graph_ctx)

        async for token in _generate_stream(context, query):
            yield token

    async def answer(self, query: str, top_k: int = TOP_K) -> str:
        route = _route(query)

        # Векторный поиск всегда; фильтруем по порогу до обращения в Postgres
        results = await self._search(query, top_k=top_k)
        chunk_ids = [cid for cid, score in results if score >= SCORE_THRESHOLD]

        if not chunk_ids and route == "dense":
            return "Недостаточно данных в базе знаний."

        if route == "global":
            try:
                chunks, graph_ctx = await asyncio.gather(
                    _fetch_chunks(chunk_ids),
                    global_search(query),
                )
            except Exception:
                chunks = await _fetch_chunks(chunk_ids)
                graph_ctx = None
        elif route == "local":
            try:
                chunks, graph_ctx = await asyncio.gather(
                    _fetch_chunks(chunk_ids),
                    local_search(query),
                )
            except Exception:
                chunks = await _fetch_chunks(chunk_ids)
                graph_ctx = None
        else:
            chunks = await _fetch_chunks(chunk_ids)
            graph_ctx = None

        if not chunks and not graph_ctx:
            return "Недостаточно данных в базе знаний."

        chunks = self._reranker.rerank(query, chunks, top_n=TOP_N)

        context = _assemble_context(chunks, graph_ctx)
        answer = await _generate(context, query)

        invalid = _verify_citations(answer, num_docs=len(chunks))
        if invalid:
            print(f"[citations] hallucinated ids: {invalid}")

        return answer
