import asyncio
import json
import os
import sys

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from embeddings.chunker import Article, chunk_article
from embeddings.embed_and_index import IndexableChunk, NewsIndexer

POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://user:password@localhost:5432/mydb")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")


async def insert_chunks(conn, chunks) -> list[int]:
    chunk_ids = []
    for chunk in chunks:
        chunk_id = await conn.fetchval(
            "INSERT INTO chunk (article_id, chunk_text, payload) VALUES ($1, $2, $3) RETURNING chunk_id",
            chunk.article_id,
            chunk.text,
            json.dumps({
                "chunk_index": chunk.chunk_index,
                "source": chunk.payload["source"],
                "published_at": chunk.payload["published_at"],
                "content_hash": chunk.payload["content_hash"],
            }),
        )
        chunk_ids.append(chunk_id)
    return chunk_ids


async def main() -> None:
    indexer = NewsIndexer(qdrant_url=QDRANT_URL, api_key=QDRANT_API_KEY)

    pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=1, max_size=3)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT article_id, author, title, arttext, arturl, mark, parsedate, createdate, types_id FROM article"
                " WHERE article_id NOT IN (SELECT DISTINCT article_id FROM chunk)"
            )

        total = len(rows)
        print(f"Статей для индексации: {total}")

        for i, row in enumerate(rows, 1):
            article = Article(
                article_id=row["article_id"],
                author=row["author"],
                title=row["title"],
                arttext=row["arttext"],
                arturl=row["arturl"],
                mark=row["mark"],
                parsedate=row["parsedate"],
                createdate=row["createdate"],
                types_id=row["types_id"],
            )

            chunks = chunk_article(article)

            async with pool.acquire() as conn:
                async with conn.transaction():
                    db_chunk_ids = await insert_chunks(conn, chunks)

            indexable = [
                IndexableChunk(
                    chunk_id=db_id,
                    article_id=chunk.article_id,
                    chunk_text=chunk.text,
                    payload={**chunk.payload, "chunk_id": db_id},
                )
                for chunk, db_id in zip(chunks, db_chunk_ids)
            ]

            indexer.index(indexable)
            if i % 100 == 0 or i == total:
                print(f"[{i}/{total}] статья {article.article_id}: {len(chunks)} чанков")

        print("Готово")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())