"""
Сквозной smoke-тест: статья → чанки → эмбеддинги → индекс → поиск.
Использует in-memory Qdrant — Docker не нужен.
"""
from datetime import date

from chunker import Article, chunk_article
from embed_and_index import IndexableChunk, NewsIndexer


ARTICLE = Article(
    article_id=1,
    title="ЦБ повысил ключевую ставку до 21%",
    source="РБК",
    published_at=date(2025, 10, 25),
    language="ru",
    content=(
        "Банк России на заседании совета директоров принял решение повысить "
        "ключевую ставку на 200 базисных пунктов — до 21% годовых. "
        "Это рекордный уровень за всю историю существования ключевой ставки в России.\n\n"
        "Регулятор объяснил решение необходимостью снижения инфляции. "
        "По данным ЦБ, годовая инфляция ускорилась до 8,5% в сентябре. "
        "Прогноз по инфляции на 2025 год повышен до 8,0–8,5%.\n\n"
        "Следующее заседание совета директоров по ключевой ставке запланировано "
        "на 20 декабря 2025 года. Аналитики ожидают, что ставка останется на "
        "текущем уровне либо будет повышена ещё раз в зависимости от инфляционной динамики."
    ),
)


def main() -> None:
    print("=== Шаг 1: чанкинг ===")
    chunks = chunk_article(ARTICLE)
    print(f"  Чанков: {len(chunks)}")
    for c in chunks:
        print(f"  [{c.position}] hash={c.content_hash}  len={len(c.text)}")
        print(f"       {c.text[:80]!r}...")

    print("\n=== Шаг 2: индексация (in-memory Qdrant) ===")
    indexer = NewsIndexer()  # без URL → in-memory

    # Имитируем chunk_id, которые Postgres выдал бы через BIGSERIAL
    indexable = [
        IndexableChunk(
            chunk_id=i + 1,
            article_id=c.article_id,
            text=c.text,
            source=ARTICLE.source,
            published_at=str(ARTICLE.published_at),
            language=ARTICLE.language,
        )
        for i, c in enumerate(chunks)
    ]
    indexer.index(indexable)
    print(f"  Проиндексировано: {len(indexable)} чанков")

    print("\n=== Шаг 3: поиск ===")
    query = "ключевая ставка Банк России"
    results = indexer.search(query, top_k=3)
    print(f"  Запрос: {query!r}")
    print(f"  Топ-3 chunk_id: {results}")
    assert results, "Поиск вернул пустой результат!"
    print("\nОК — пайплайн работает.")


if __name__ == "__main__":
    main()