import psycopg2
from embeddings.chunker import Article, chunk_article
from embeddings.embed_and_index import IndexableChunk, NewsIndexer
from db.insertnews import insert_chunks

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "newsdb",
    "user": "admin",
    "password": "admin"
}

def main():
    indexer = NewsIndexer(qdrant_url="http://localhost:6333")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # 1. Берём статьи из Postgres
    cur.execute("""
        SELECT article_id, author, title, arttext, arturl,
               mark, parsedate, createdate, types_id
        FROM article
    """)
    rows = cur.fetchall()

    for row in rows:
        article = Article(
            article_id=row[0],
            author=row[1],
            title=row[2],
            arttext=row[3],
            arturl=row[4],
            mark=row[5],
            parsedate=row[6],
            createdate=row[7],
            types_id=row[8],
        )

        # 2. Нарезаем на чанки
        chunks = chunk_article(article)

        # 3. Пишем чанки в Postgres → получаем реальные chunk_id
        db_chunk_ids = insert_chunks(cur, chunks)
        conn.commit()

        # 4. Собираем IndexableChunk с настоящими id
        indexable = [
            IndexableChunk(
                chunk_id=db_id,
                article_id=chunk.article_id,
                chunk_text=chunk.text,
                payload={**chunk.payload, "chunk_id": db_id}
            )
            for chunk, db_id in zip(chunks, db_chunk_ids)
        ]

        # 5. Индексируем в Qdrant
        indexer.index(indexable)
        print(f"Проиндексирована статья {article.article_id}: {len(chunks)} чанков")

    cur.close()
    conn.close()
    print("Готово")

if __name__ == "__main__":
    main()