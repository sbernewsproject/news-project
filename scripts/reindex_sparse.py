"""
Добавляет BM25 sparse-векторы к уже проиндексированным чанкам в Qdrant.
Dense-векторы не трогает — только дописывает "bm25" поле.

Запуск:
    QDRANT_URL=http://localhost:6333 QDRANT_API_KEY=password \
    POSTGRES_DSN=postgresql://user:password@localhost:25432/mydb \
    PYTHONPATH=. .venv/bin/python3 scripts/reindex_sparse.py
"""

import asyncio
import os
import sys

import asyncpg
from qdrant_client import QdrantClient
from qdrant_client.models import (
    SparseVector,
    SparseVectorParams,
    SparseIndexParams,
    PointVectors,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from embeddings.embed_and_index import COLLECTION

try:
    from fastembed import SparseTextEmbedding
except ImportError:
    print("Установи fastembed: pip install fastembed")
    sys.exit(1)

POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://user:password@localhost:5432/mydb")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
BATCH = int(os.getenv("BATCH_SIZE", "512"))


async def main() -> None:
    qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=120)
    encoder = SparseTextEmbedding(model_name="Qdrant/bm25")

    # Добавить sparse конфиг в коллекцию
    print("Обновляем конфиг коллекции...")
    try:
        qdrant.update_collection(
            collection_name=COLLECTION,
            sparse_vectors_config={
                "bm25": SparseVectorParams(index=SparseIndexParams(on_disk=False))
            },
        )
    except Exception as e:
        print(f"  (конфиг уже есть или ошибка: {e})")

    # Читаем все чанки из Postgres
    print("Читаем чанки из Postgres...")
    conn = await asyncpg.connect(POSTGRES_DSN, statement_cache_size=0)
    try:
        rows = await conn.fetch("SELECT chunk_id, chunk_text FROM chunk ORDER BY chunk_id")
    finally:
        await conn.close()

    total = len(rows)
    print(f"Всего чанков: {total}")

    for start in range(0, total, BATCH):
        batch = rows[start : start + BATCH]
        texts = [r["chunk_text"] for r in batch]
        chunk_ids = [r["chunk_id"] for r in batch]

        sparse_vecs = list(encoder.embed(texts))

        points = [
            PointVectors(
                id=cid,
                vector={
                    "bm25": SparseVector(
                        indices=sv.indices.tolist(),
                        values=sv.values.tolist(),
                    )
                },
            )
            for cid, sv in zip(chunk_ids, sparse_vecs)
        ]

        qdrant.update_vectors(collection_name=COLLECTION, points=points)

        done = min(start + BATCH, total)
        print(f"  [{done}/{total}] обновлено", end="\r")

    print(f"\nГотово — {total} чанков обновлено с BM25 sparse-векторами.")


if __name__ == "__main__":
    asyncio.run(main())