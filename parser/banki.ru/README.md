# banki.ru — Банки

Парсер карточек банков и отзывов с banki.ru.

## Запуск

Все команды выполняются из корня репозитория.

**Собрать список банков:**
```bash
python3 parser/parser/main.py parser/banki.ru sitemap
```

**Спарсить (тест — 5 банков):**
```bash
python3 parser/parser/main.py parser/banki.ru parse --limit 5
```

**Спарсить повторно те же банки:**
```bash
python3 parser/parser/main.py parser/banki.ru parse --limit 5 --fresh
```

**Полный прогон:**
```bash
python3 parser/parser/main.py parser/banki.ru parse
```

## Источники данных

| Шаг | URL | Что берём |
|-----|-----|-----------|
| Список банков | `/sitemap/bankiru_banks_bank` | slug'и всех банков (~360 записей) |
| Карточка банка | `/banks/bank/{slug}/` | название, лицензия, ОГРН, год основания, продукты |
| Страница отзывов | `/services/responses/bank/{slug}/` | оценка, кол-во отзывов, % решённых проблем, место в рейтинге, превью отзывов |

## Формат результата

`parsed_articles.json` — список объектов, по одному на банк:

```json
{
  "url": "https://www.banki.ru/banks/bank/sberbank/",
  "title": "Сбербанк",
  "section": "bank",
  "slug": "sberbank",
  "name": "Сбербанк",
  "license": "1481",
  "ogrn": "1027700132195",
  "founded_year": "1991",
  "rating_place_raw": "34 место",
  "rating_place_block": "34 место из 308 банка",
  "financial_rating_raw": "1 место по России",
  "avg_score": "2.4557505",
  "reviews_total": "5106",
  "solved_pct": "33.68%",
  "products": ["РКО", "Автокредиты", "Кредитные карты", "Вклады", "Ипотека"],
  "reviews_fetched": 50,
  "reviews": [
    {
      "org_slug": "sberbank",
      "review_id": "13165699",
      "review_url": "/services/responses/bank/response/13165699/",
      "title": "Чарджбэк",
      "score": "5",
      "date": "17.06.2026 14:57",
      "text_preview": "Случилась неприятная ситуация...",
      "badges": ["Зачтено", "Отзыв проверен", "Ответ банка"]
    }
  ],
  "parsed_at": "2026-06-19T12:00:00"
}
```

## Известные особенности

- `reviews_fetched` может быть больше `reviews_total` — страница отзывов показывает общую ленту, не только отзывы конкретного банка. Фильтрация по `org_slug` планируется.
- У банков с малым числом отзывов `avg_score` и `reviews_total` могут быть пустыми — JSON-LD на странице не содержит `aggregateRating`.
- Ссылки на полный текст отзывов доступны через `review_url`. Отдельный парсинг полного отзыва реализован в `parsers.py::fetch_review_detail`, но в основной пайплайн пока не включён.
- Список банков содержит ~360 записей (только банки с лицензией/ОГРН, ЖК и застройщики отсеиваются автоматически).
