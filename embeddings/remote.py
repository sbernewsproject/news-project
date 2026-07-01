"""
Клиент эмбеддингов запроса через Ollama (`/api/embeddings`).

Модели живут на GPU-хосте, поэтому VPS НЕ грузит SentenceTransformer в процесс,
а ходит за вектором по HTTP. Префикс "query: " и L2-нормализация повторяют то,
как NewsIndexer._embed_query кодирует запрос (см. embeddings/embed_and_index.py),
чтобы вектор был совместим с проиндексированными в Qdrant пассажами (метрика DOT).
"""

import math
import os

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
# Отдельная эмбеддинг-модель (не путать с OLLAMA_MODEL — это LLM для генерации).
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")

_QUERY_PREFIX = "query: "


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


async def embed_query(query: str, *, timeout: float = 30.0) -> list[float]:
    """Возвращает нормированный вектор запроса для поиска в Qdrant.

    Бросает исключение при недоступности Ollama — вызывающий код (гибридный
    поиск) ловит его и деградирует на чистый FTS.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": OLLAMA_EMBED_MODEL, "input": f"{_QUERY_PREFIX}{query}"},
        )
        resp.raise_for_status()
        embedding = resp.json()["embeddings"][0]
    return _l2_normalize(embedding)
