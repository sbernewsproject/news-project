"""Проверка графа на малой выборке (20 статей)."""
import asyncio
import os

os.environ.setdefault("GRAPH_WORKING_DIR", "/tmp/ragu_test")

from graph.build_graph import insert_articles, get_knowledge_graph


async def main():
    import asyncpg
    dsn = os.getenv("POSTGRES_DSN", "postgresql://user:password@localhost:5432/mydb")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT title, arttext FROM article ORDER BY createdate DESC LIMIT 20"
        )
    finally:
        await conn.close()

    texts = [f"{r['title']}\n\n{r['arttext']}" for r in rows]
    print(f"Тестируем на {len(texts)} статьях...")
    await insert_articles(texts)

    kg = get_knowledge_graph()
    print(f"Готово. Проверяем граф в {os.environ['GRAPH_WORKING_DIR']}")


if __name__ == "__main__":
    asyncio.run(main())