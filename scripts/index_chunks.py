"""
Читает чанки из таблицы chunk и индексирует их в Qdrant.
Используется для первичной или повторной индексации без перечанкования.

Переменные окружения (или значения по умолчанию):
  POSTGRES_DSN  — postgresql://news:news@localhost:5432/newsdb
  QDRANT_URL    — http://localhost:6333
  BATCH_SIZE    — 256
"""

import asyncio
import os
import sys

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from embeddings.embed_and_index import IndexableChunk, NewsIndexer

POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://news:news@localhost:5432/newsdb")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "256"))


async def main() -> None:
    print(f"Подключение к Postgres: {POSTGRES_DSN}")
    print(f"Qdrant: {QDRANT_URL}")

    conn = await asyncpg.connect(POSTGRES_DSN)
    try:
        indexer = NewsIndexer(qdrant_url=QDRANT_URL)
        total = 0
        offset = 0

        while True:
            rows = await conn.fetch(
                "SELECT chunk_id, article_id, chunk_text, payload FROM chunk ORDER BY chunk_id LIMIT $1 OFFSET $2",
                BATCH_SIZE, offset,
            )
            if not rows:
                break

            batch = [
                IndexableChunk(
                    chunk_id=row["chunk_id"],
                    article_id=row["article_id"],
                    chunk_text=row["chunk_text"],
                    payload={**row["payload"], "chunk_id": row["chunk_id"]},
                )
                for row in rows
            ]
            indexer.index(batch)
            total += len(batch)
            offset += len(batch)
            print(f"  Проиндексировано: {total} чанков", end="\r")

        print(f"\nГотово. Всего проиндексировано: {total} чанков.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())