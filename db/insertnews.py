import asyncio
import json
import os
import sys

import asyncpg
import ijson

DSN = os.getenv("POSTGRES_DSN", "postgresql://user:password@localhost:5432/mydb")

BATCH_SIZE = 500


def _article_type(item: dict) -> str:
    return "Отзыв" if item.get("section") == "bank_review" else "Новость"


def _mark(item: dict) -> int | None:
    score = item.get("score")
    try:
        return int(score) if score is not None and score != "" else None
    except (ValueError, TypeError):
        return None


async def get_or_create_cached(conn, cache: dict, table: str, id_col: str, name_col: str, name: str) -> int:
    if name not in cache:
        row = await conn.fetchrow(f"SELECT {id_col} FROM {table} WHERE {name_col} = $1", name)
        if row:
            cache[name] = row[0]
        else:
            cache[name] = await conn.fetchval(
                f"INSERT INTO {table} ({name_col}) VALUES ($1) RETURNING {id_col}", name
            )
    return cache[name]


async def insert_batch(conn, batch: list, theme_cache: dict, types_cache: dict) -> tuple[int, int]:
    urls = [item.get("url", "") for item in batch]
    existing = await conn.fetch(
        "SELECT arturl FROM article WHERE arturl = ANY($1::text[])", urls
    )
    existing_urls = {row["arturl"] for row in existing}

    new_items = [item for item in batch if item.get("url", "") not in existing_urls]
    skipped = len(batch) - len(new_items)

    if not new_items:
        return 0, skipped

    rows = []
    theme_ids = []
    for item in new_items:
        section  = item.get("section") or "Без раздела"
        atype    = _article_type(item)
        theme_id = await get_or_create_cached(conn, theme_cache, "theme", "theme_id", "theme_name", section)
        types_id = await get_or_create_cached(conn, types_cache, "types", "types_id", "types_name", atype)
        rows.append((
            item.get("author") or "Неизвестен",
            item.get("title", ""),
            item.get("body", ""),
            item.get("url", ""),
            _mark(item),
            item.get("parsed_at") or "",
            item.get("date_published") or "",
            types_id,
        ))
        theme_ids.append(theme_id)

    async with conn.transaction():
        article_ids = await conn.fetch(
            """
            INSERT INTO article (author, title, arttext, arturl, mark, parsedate, createdate, types_id)
            SELECT
                unnest($1::text[]),
                unnest($2::text[]),
                unnest($3::text[]),
                unnest($4::text[]),
                unnest($5::int[]),
                unnest($6::text[]),
                unnest($7::text[]),
                unnest($8::int[])
            ON CONFLICT (arturl) DO NOTHING
            RETURNING article_id
            """,
            [r[0] for r in rows],
            [r[1] for r in rows],
            [r[2] for r in rows],
            [r[3] for r in rows],
            [r[4] for r in rows],
            [r[5] for r in rows],
            [r[6] for r in rows],
            [r[7] for r in rows],
        )

        if article_ids:
            await conn.executemany(
                "INSERT INTO article_theme (article_id, theme_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                [(row["article_id"], tid) for row, tid in zip(article_ids, theme_ids)],
            )

    return len(article_ids), skipped


async def process(json_path: str) -> None:
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_article_arturl ON article(arturl)"
        )

        theme_cache: dict[str, int] = {}
        types_cache: dict[str, int] = {}
        inserted = 0
        skipped = 0
        processed = 0
        batch = []

        print(f"Читаю {json_path} потоково (без загрузки в память)...")

        with open(json_path, "rb") as f:
            for item in ijson.items(f, "item"):
                batch.append(item)
                if len(batch) >= BATCH_SIZE:
                    ins, skp = await insert_batch(conn, batch, theme_cache, types_cache)
                    inserted += ins
                    skipped += skp
                    processed += len(batch)
                    print(f"[{processed:,}] вставлено {inserted:,}, пропущено {skipped:,}")
                    batch = []

        if batch:
            ins, skp = await insert_batch(conn, batch, theme_cache, types_cache)
            inserted += ins
            skipped += skp
            processed += len(batch)

        print(f"\nГотово: вставлено {inserted:,}, пропущено {skipped:,}, всего обработано {processed:,}")
    finally:
        await conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python3 insertnews.py <путь_к_файлу.json>")
        sys.exit(1)
    asyncio.run(process(sys.argv[1]))
