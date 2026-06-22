import json
import psycopg2

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "mydb",
    "user": "user",
    "password": "password"
}

ARTICLE_TYPE = "Новость"


def get_or_create(cursor, table: str, id_col: str, name_col: str, name: str) -> int:
    cursor.execute(
        f"SELECT {id_col} FROM {table} WHERE {name_col} = %s",
        (name,)
    )
    row = cursor.fetchone()
    if row:
        return row[0]
    cursor.execute(
        f"INSERT INTO {table} ({name_col}) VALUES (%s) RETURNING {id_col}",
        (name,)
    )
    return cursor.fetchone()[0]


def insert_article(cursor, item: dict, types_id: int) -> int:
    cursor.execute("""
        INSERT INTO article (author, title, arttext, arturl, mark, parsedate, createdate, types_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING article_id
    """, (
        item.get("author") or "Неизвестен",
        item.get("title", ""),
        item.get("body", ""),
        item.get("url", ""),
        None,
        item.get("parsed_at") or "",
        item.get("date_published") or "",
        types_id
    ))
    return cursor.fetchone()[0]


def link_article_theme(cursor, article_id: int, theme_id: int):
    cursor.execute("""
        INSERT INTO article_theme (article_id, theme_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
    """, (article_id, theme_id))


def load_json(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]


def process(json_path: str):
    articles = load_json(json_path)

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn:
            with conn.cursor() as cur:
                inserted = 0
                skipped = 0

                types_id = get_or_create(cur, "types", "types_id", "types_name", ARTICLE_TYPE)

                for item in articles:
                    url = item.get("url", "")

                    cur.execute("SELECT 1 FROM article WHERE arturl = %s", (url,))
                    if cur.fetchone():
                        print(f"[skip] уже есть: {url}")
                        skipped += 1
                        continue

                    section = item.get("section") or "Без раздела"
                    theme_id = get_or_create(cur, "theme", "theme_id", "theme_name", section)

                    article_id = insert_article(cur, item, types_id)

                    link_article_theme(cur, article_id, theme_id)

                    inserted += 1
                    print(f"[ok] article_id={article_id} | theme='{section}' | {item.get('title', '')[:55]}")

                print(f"\nГотово: вставлено {inserted}, пропущено {skipped}")
    finally:
        conn.close()


if __name__ == "__main__":
    process("parsed_articles.json")