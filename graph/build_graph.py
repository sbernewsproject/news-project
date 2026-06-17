"""
Строит и сохраняет граф знаний из текстов статей через LightRAG.
LightRAG вызывает Ollama для извлечения сущностей и связей, затем
записывает граф на диск в GRAPH_WORKING_DIR.
Передавать сюда нужно полные тексты статей — LightRAG сам делает чанкинг внутри.
"""

import asyncio
import os
from pathlib import Path
from typing import Optional

from lightrag import LightRAG, QueryParam
from lightrag.llm.ollama import ollama_model_complete
from lightrag.utils import EmbeddingFunc
from sentence_transformers import SentenceTransformer

WORKING_DIR = os.getenv("GRAPH_WORKING_DIR", "./ragu_working_dir")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:32b")

# Синглтоны уровня модуля — инициализируются один раз на процесс
_embed_model: Optional[SentenceTransformer] = None
_rag_instance: Optional[LightRAG] = None


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer("BAAI/bge-m3")
    return _embed_model


async def _embed(texts: list[str]) -> list[list[float]]:
    model = _get_embed_model()
    return model.encode(texts, normalize_embeddings=True, batch_size=32).tolist()


def get_rag() -> LightRAG:
    """Возвращает синглтон LightRAG (подхватывает граф с диска, если уже построен)."""
    global _rag_instance
    if _rag_instance is None:
        Path(WORKING_DIR).mkdir(parents=True, exist_ok=True)
        _rag_instance = LightRAG(
            working_dir=WORKING_DIR,
            llm_model_func=ollama_model_complete,
            llm_model_name=OLLAMA_MODEL,
            llm_model_max_async=2,
            llm_model_kwargs={
                "host": OLLAMA_URL,
                "options": {"num_ctx": 32768},
            },
            embedding_func=EmbeddingFunc(
                embedding_dim=1024,
                max_token_size=512,
                func=_embed,
            ),
            addon_params={"language": "Russian"},
        )
    return _rag_instance


async def insert_articles(texts: list[str]) -> None:
    """
    Загружает тексты статей в граф. LightRAG через Ollama извлекает
    сущности и связи, затем записывает результат в WORKING_DIR.
    Безопасно вызывать повторно — уже виденные тексты пропускаются по хэшу.
    """
    rag = get_rag()
    await rag.ainsert(texts)



# CLI: python -m graph.build_graph  — загружает все статьи из Postgres

async def _build_from_postgres() -> None:
    import asyncpg

    dsn = os.getenv("POSTGRES_DSN", "postgresql://news:news@localhost:5432/newsdb")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT title, content FROM articles ORDER BY published_at DESC"
        )
    finally:
        await conn.close()

    texts = [f"{r['title']}\n\n{r['content']}" for r in rows]
    print(f"Загружаем {len(texts)} статей в граф...")
    await insert_articles(texts)
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(_build_from_postgres())