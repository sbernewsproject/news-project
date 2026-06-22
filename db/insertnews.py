import asyncio
import json
import os

import asyncpg

DSN = os.getenv("POSTGRES_DSN", "postgresql://user:password@localhost:5432/mydb")

ARTICLE_TYPE = "Новость"


async def get_or_create(conn, table: str, id_col: str, name_col: str, name: str) -> int:
    row = await conn.fetchrow(
        f"SELECT {id_col} FROM {table} WHERE {name_col} = $1", name
    )
    if row:
        return row[0]
    return await conn.fetchval(
        f"INSERT INTO {table} ({name_col}) VALUES ($1) RETURNING {id_col}", name
    )


async def insert_article(conn, item: dict, types_id: int) -> int:
    return await conn.fetchval("""
        INSERT INTO article (author, title, arttext, arturl, mark, parsedate, createdate, types_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING article_id
    """,
        item.get("author") or "Неизвестен",
        item.get("title", ""),
        item.get("body", ""),
        item.get("url", ""),
        None,
        item.get("parsed_at") or "",
        item.get("date_published") or "",
        types_id,
    )


async def process(json_path: str) -> None:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    articles = data if isinstance(data, list) else [data]

    conn = await asyncpg.connect(DSN)
    try:
        inserted = 0
        skipped = 0

        types_id = await get_or_create(conn, "types", "types_id", "types_name", ARTICLE_TYPE)

        for item in articles:
            url = item.get("url", "")

            exists = await conn.fetchval("SELECT 1 FROM article WHERE arturl = $1", url)
            if exists:
                print(f"[skip] уже есть: {url}")
                skipped += 1
                continue

            section = item.get("section") or "Без раздела"
            theme_id = await get_or_create(conn, "theme", "theme_id", "theme_name", section)

            async with conn.transaction():
                article_id = await insert_article(conn, item, types_id)
                await conn.execute(
                    "INSERT INTO article_theme (article_id, theme_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    article_id, theme_id,
                )

            inserted += 1
            print(f"[ok] article_id={article_id} | theme='{section}' | {item.get('title', '')[:55]}")

        print(f"\nГотово: вставлено {inserted}, пропущено {skipped}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(process("parsed_articles.json"))