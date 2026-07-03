import asyncio
import json
import os
import sys

import asyncpg
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from embeddings.chunker import Article, chunk_article
from embeddings.embed_and_index import COLLECTION, VECTOR_SIZE, IndexableChunk
from embeddings.remote import batch_embed_text

POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://user:password@localhost:5432/mydb")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
OLLAMA_URL = os.getenv("OLLAMA_URL")

ARTICLE_BATCH = 200


def _ensure_collection(qdrant: QdrantClient) -> None:
    names = {c.name for c in qdrant.get_collections().collections}
    if COLLECTION not in names:
        qdrant.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.DOT),
        )


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
    use_remote = bool(OLLAMA_URL)

    if use_remote:
        print(f"Режим: удалённый эмбедер через Ollama ({OLLAMA_URL})")
        qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=120)
        _ensure_collection(qdrant)
    else:
        print("Режим: локальный BGE-M3")
        from embeddings.embed_and_index import NewsIndexer
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

        for batch_start in range(0, total, ARTICLE_BATCH):
            batch_rows = rows[batch_start:batch_start + ARTICLE_BATCH]

            all_chunks = []
            for row in batch_rows:
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
                all_chunks.extend(chunk_article(article))

            async with pool.acquire() as conn:
                async with conn.transaction():
                    db_chunk_ids = await insert_chunks(conn, all_chunks)

            indexable = [
                IndexableChunk(
                    chunk_id=db_id,
                    article_id=chunk.article_id,
                    chunk_text=chunk.text,
                    payload={**chunk.payload, "chunk_id": db_id},
                )
                for chunk, db_id in zip(all_chunks, db_chunk_ids)
            ]

            if use_remote:
                prefixed = [f"passage: {c.chunk_text}" for c in indexable]
                vectors = await batch_embed_text(prefixed)
                points = [
                    PointStruct(id=c.chunk_id, vector=v, payload=c.payload)
                    for c, v in zip(indexable, vectors)
                ]
                qdrant.upsert(collection_name=COLLECTION, points=points)
            else:
                indexer.index(indexable)

            n = min(batch_start + ARTICLE_BATCH, total)
            print(f"[{n}/{total}] обработано статей")

        print("Готово")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())