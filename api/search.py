"""
Гибридный поиск по статьям: Postgres FTS + семантика (Qdrant) со слиянием RRF.

Возвращает упорядоченный список article_id; карточки по этим id грузит роутер
(api/articles.py). Если семантическая часть недоступна (Ollama/Qdrant не отвечают
или Qdrant пуст), поиск деградирует на чистый FTS.
"""

import asyncio
import os
from typing import Optional

import asyncpg
from qdrant_client import QdrantClient

from api.db import get_pool
from embeddings.remote import embed_query

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION = "news_chunks"

RRF_K = 60          # константа сглаживания reciprocal rank fusion
CANDIDATES = 100    # сколько кандидатов берём из каждого источника до слияния

_qdrant: Optional[QdrantClient] = None


def _client() -> QdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _qdrant


async def _fts_ids(query: str, limit: int) -> list[int]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT article_id
        FROM article
        WHERE tsv @@ websearch_to_tsquery('russian', $1)
        ORDER BY ts_rank(tsv, websearch_to_tsquery('russian', $1)) DESC
        LIMIT $2
        """,
        query,
        limit,
    )
    return [r["article_id"] for r in rows]


def _qdrant_search(vector: list[float], limit: int) -> list[int]:
    """Синхронный вызов Qdrant → article_id в порядке релевантности (без дублей)."""
    results = _client().query_points(
        collection_name=COLLECTION,
        query=vector,
        limit=limit,
        with_payload=["article_id"],
    )
    seen: set[int] = set()
    ordered: list[int] = []
    for point in results.points:
        aid = (point.payload or {}).get("article_id")
        if aid is None or aid in seen:
            continue
        seen.add(aid)
        ordered.append(int(aid))
    return ordered


async def _semantic_ids(query: str, limit: int) -> list[int]:
    """article_id по семантике; при любой ошибке (Ollama/Qdrant) — пустой список."""
    try:
        vector = await embed_query(query)
        return await asyncio.to_thread(_qdrant_search, vector, limit)
    except Exception:
        return []


def _rrf(*ranked_lists: list[int]) -> list[int]:
    scores: dict[int, float] = {}
    for ids in ranked_lists:
        for rank, aid in enumerate(ids):
            scores[aid] = scores.get(aid, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda a: scores[a], reverse=True)


async def hybrid_search(query: str, limit: int) -> list[int]:
    """Упорядоченный по релевантности список article_id (длиной до limit)."""
    fts_ids, sem_ids = await asyncio.gather(
        _fts_ids(query, CANDIDATES),
        _semantic_ids(query, CANDIDATES),
    )
    return _rrf(fts_ids, sem_ids)[:limit]
