"""
Основная RAG-цепочка:
  1. Роутинг запроса → local / global / dense
  2. Гибридный поиск: Dense (Qdrant) + Sparse BM25 (Qdrant) + FTS (Postgres) + HyDE
  3. Reranker отбирает TOP_N лучших чанков
  4. Генерация ответа через Ollama
"""

import asyncio
import json as _json
import os
import re
from typing import AsyncGenerator, Optional

import asyncpg
import httpx

from embeddings.embed_and_index import NewsIndexer, Reranker, COLLECTION
from embeddings.remote import embed_query as _remote_embed_query
from qdrant_client import QdrantClient

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:30b-a3b")
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://user:password@localhost:5432/mydb")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

TOP_K = 50
TOP_N = 10
SCORE_THRESHOLD = 0.5
_RRF_K = 60

# HyDE: генерирует гипотетический документ перед поиском.
# Улучшает recall на сложных вопросах, но добавляет один LLM-вызов.
# Включать после перехода на быструю модель (MoE/малую).
USE_HYDE = os.getenv("USE_HYDE", "false").lower() == "true"

SYSTEM_PROMPT = """\
Ты — аналитик, создающий новостные сводки на русском языке.
Правила:
- Используй ТОЛЬКО информацию из предоставленного контекста.
- Не придумывай факты, цифры, имена.
- Ссылайся на источники в формате [id] — число соответствует id тега <doc>.
- Если в контексте недостаточно данных, ответь: "Недостаточно данных в базе знаний."
- Пиши кратко, структурированно, по-русски.\
"""

_GLOBAL_MARKERS = ("тенденци", "обзор", "ситуаци", "в целом", "в общем", "тренд", "динамик")
_LOCAL_MARKERS = ("кто ", "кто,", "кого", "какой", "назов", "перечисл", "какие компани")


def _route(query: str) -> str:
    q = query.lower()
    if any(m in q for m in _GLOBAL_MARKERS) or len(query) > 100:
        return "global"
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


def _assemble_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        date_str = str(c.get("published_at", ""))[:10]
        parts.append(
            f'<doc id="{i}" source="{c["source"]}" date="{date_str}">\n'
            f'{c["text"]}\n</doc>'
        )
    return "\n\n".join(parts)


def _verify_citations(answer: str, num_docs: int) -> list[int]:
    cited = {int(m) for m in re.findall(r'\[(\d+)]', answer)}
    return [c for c in cited if c < 1 or c > num_docs]


def _rrf(*ranked_lists: list[int]) -> list[int]:
    scores: dict[int, float] = {}
    for ids in ranked_lists:
        for rank, cid in enumerate(ids):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
    return sorted(scores, key=lambda c: scores[c], reverse=True)


async def _fts_search(query: str, limit: int) -> list[int]:
    try:
        conn = await asyncpg.connect(POSTGRES_DSN)
        try:
            rows = await conn.fetch(
                """
                SELECT chunk_id
                FROM chunk
                WHERE tsv @@ websearch_to_tsquery('russian', $1)
                ORDER BY ts_rank(tsv, websearch_to_tsquery('russian', $1)) DESC
                LIMIT $2
                """,
                query,
                limit,
            )
            return [r["chunk_id"] for r in rows]
        finally:
            await conn.close()
    except Exception:
        return []


async def _hyde_vector(query: str) -> Optional[list[float]]:
    """HyDE: генерирует гипотетический фрагмент статьи → эмбеддинг для поиска."""
    try:
        prompt = (
            f"Напиши короткий фрагмент новостной статьи, который отвечает на вопрос: {query}\n"
            "Только текст фрагмента, без объяснений."
        )
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "think": False,
                },
            )
            resp.raise_for_status()
        content = resp.json()["message"]["content"]
        if "</think>" in content:
            content = content[content.index("</think>") + 8:].strip()
        return await _remote_embed_query(content)
    except Exception:
        return None


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
                },
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
    except Exception:
        return f"[Ollama недоступен] Найдено {context.count('<doc')} релевантных фрагментов."


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
        if not self._use_remote_embed:
            return self._indexer.search(query, top_k=top_k)

        # Параллельно: вектор запроса + FTS + (HyDE если включён)
        gather_tasks: list = [_remote_embed_query(query), _fts_search(query, top_k)]
        if USE_HYDE:
            gather_tasks.append(_hyde_vector(query))

        step1 = await asyncio.gather(*gather_tasks)
        query_vec: list[float] = step1[0]
        fts_ids: list[int] = step1[1]
        hyde_vec: Optional[list[float]] = step1[2] if USE_HYDE else None

        # Qdrant: dense-поиск
        qdrant_results = await asyncio.to_thread(
            self._qdrant.query_points,
            collection_name=COLLECTION,
            query=query_vec,
            limit=top_k,
        )

        qdrant_scored = {r.id: r.score for r in qdrant_results.points}
        qdrant_ids = list(qdrant_scored)

        # HyDE: дополнительный поиск по гипотетическому документу
        if hyde_vec:
            hyde_results = await asyncio.to_thread(
                self._qdrant.query_points,
                collection_name=COLLECTION,
                query=hyde_vec,
                limit=top_k,
            )
            hyde_ids = [r.id for r in hyde_results.points]
            hyde_scored = {r.id: r.score for r in hyde_results.points}
            merged = _rrf(qdrant_ids, hyde_ids, fts_ids)[:top_k]
            all_scored = {**hyde_scored, **qdrant_scored}
        else:
            merged = _rrf(qdrant_ids, fts_ids)[:top_k]
            all_scored = qdrant_scored

        return [(cid, all_scored.get(cid, SCORE_THRESHOLD)) for cid in merged]

    async def stream_answer(self, query: str, top_k: int = TOP_K) -> AsyncGenerator[str, None]:
        yield "\x00ищу статьи\x00"
        results = await self._search(query, top_k=top_k)
        chunk_ids = [cid for cid, score in results if score >= SCORE_THRESHOLD]

        if not chunk_ids:
            yield "Недостаточно данных в базе знаний."
            return

        yield "\x00загружаю контекст\x00"
        chunks = await _fetch_chunks(chunk_ids)
        if not chunks:
            yield "Недостаточно данных в базе знаний."
            return

        yield "\x00ранжирую результаты\x00"
        chunks = self._reranker.rerank(query, chunks, top_n=TOP_N)
        context = _assemble_context(chunks)

        yield "\x00формирую ответ\x00"
        async for token in _generate_stream(context, query):
            yield token

    async def answer(self, query: str, top_k: int = TOP_K) -> str:
        results = await self._search(query, top_k=top_k)
        chunk_ids = [cid for cid, score in results if score >= SCORE_THRESHOLD]

        if not chunk_ids:
            return "Недостаточно данных в базе знаний."

        chunks = await _fetch_chunks(chunk_ids)
        if not chunks:
            return "Недостаточно данных в базе знаний."

        chunks = self._reranker.rerank(query, chunks, top_n=TOP_N)
        context = _assemble_context(chunks)
        answer = await _generate(context, query)

        invalid = _verify_citations(answer, num_docs=len(chunks))
        if invalid:
            print(f"[citations] hallucinated ids: {invalid}")

        return answer