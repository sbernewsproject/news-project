# banki.ru — Отзывы о банках

Парсер отзывов с banki.ru. Каждый отзыв сохраняется как отдельная запись в формате новостной статьи.

## Запуск

Все команды выполняются из корня репозитория.

**Собрать URL отзывов (все банки):**
```bash
python3 parser/parser/main.py parser/banki.ru sitemap
```

**Собрать URL отзывов (тест — первые N банков):**
```bash
python3 parser/parser/main.py parser/banki.ru sitemap --limit 5
```

**Спарсить отзывы (тест — первые N отзывов):**
```bash
python3 parser/parser/main.py parser/banki.ru parse --limit 20
```

**Полный прогон:**
```bash
python3 parser/parser/main.py parser/banki.ru all
```

**Начать заново (игнорировать кеш):**
```bash
python3 parser/parser/main.py parser/banki.ru sitemap --fresh
python3 parser/parser/main.py parser/banki.ru parse --fresh
```

## Источники данных

| Шаг | URL | Что берём |
|-----|-----|-----------|
| Список банков | `/sitemap/bankiru_banks_bank` | slug'и всех банков (~360 записей) |
| Листинг отзывов | `/services/responses/bank/{slug}/` | URL каждого отзыва (все страницы) |
| Полный отзыв | `/services/responses/bank/response/{id}/` | заголовок, автор, дата, текст, оценка |

## Формат результата

`parsed_articles.json` — список объектов, по одному на отзыв:

```json
{
  "url": "https://www.banki.ru/services/responses/bank/response/13018216/",
  "title": "Неуважение к клиентам, неинформативный сайт",
  "author": "user-576422661391",
  "date_published": "30.03.2026 13:44",
  "section": "bank_review",
  "bank_name": "МОРСКОЙ БАНК",
  "body": "Хотели стать клиентами банка...",
  "body_length": 408,
  "score": "2",
  "parsed_at": "2026-06-19T15:41:47"
}
```

## Известные особенности

- `--limit` на шаге `sitemap` ограничивает количество банков, а не отзывов.
- `--limit` на шаге `parse` ограничивает количество отзывов.
- Банки без отзывов пропускаются автоматически на шаге sitemap.
- `score` — строка от `"1"` до `"5"`.
