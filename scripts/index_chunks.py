"""
Читает чанки из таблицы chunk и индексирует их в Qdrant.
Используется для первичной или повторной индексации без перечанкования.

Переменные окружения (или значения по умолчанию):
  POSTGRES_DSN  — postgresql://news:news@localhost:5432/newsdb
  QDRANT_URL    — http://localhost:6333
  BATCH_SIZE    — 256
"""

import os
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from embeddings.embed_and_index import IndexableChunk, NewsIndexer

POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://news:news@localhost:5432/newsdb")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "256"))


def iter_chunks(conn, batch_size: int):
    with conn.cursor(name="chunks_cursor", cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT chunk_id, article_id, chunk_text, payload FROM chunk ORDER BY chunk_id")
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            yield [
                IndexableChunk(
                    chunk_id=row["chunk_id"],
                    article_id=row["article_id"],
                    chunk_text=row["chunk_text"],
                    payload={**row["payload"], "chunk_id": row["chunk_id"]},
                )
                for row in rows
            ]


def main() -> None:
    print(f"Подключение к Postgres: {POSTGRES_DSN}")
    print(f"Qdrant: {QDRANT_URL}")

    conn = psycopg2.connect(POSTGRES_DSN)
    try:
        indexer = NewsIndexer(qdrant_url=QDRANT_URL)

        total = 0
        for batch in iter_chunks(conn, BATCH_SIZE):
            indexer.index(batch)
            total += len(batch)
            print(f"  Проиндексировано: {total} чанков", end="\r")

        print(f"\nГотово. Всего проиндексировано: {total} чанков.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
