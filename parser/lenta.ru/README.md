# Lenta.ru

## Как работает

Стандартный двухшаговый парсер: сначала собирает ссылки через XML sitemap (gzip), потом парсит каждую статью.

| Шаг | Что делает |
|-----|-----------|
| `sitemap` | Обходит `lenta.ru/sitemap.xml.gz` и извлекает ссылки на `/news/` и `/articles/` |
| `parse` | Загружает страницу каждой статьи и извлекает данные из кастомного парсера `parser.py` |

Скорость парсинга: **~50 статей/сек** (100 async-соединений, без задержки).

## Запуск

Все команды выполняются из корня репозитория.

**Тест — 2 sitemap'а:**
```bash
python3 parser/parser/main.py parser/lenta.ru sitemap --limit 2
```

**Полный сбор ссылок:**
```bash
python3 parser/parser/main.py parser/lenta.ru sitemap
```

**Тест парсинга — 5 статей:**
```bash
python3 parser/parser/main.py parser/lenta.ru parse --limit 5
```

**Повторить те же 5 (игнорировать прогресс):**
```bash
python3 parser/parser/main.py parser/lenta.ru parse --limit 5 --fresh
```

**Полный парсинг:**
```bash
python3 parser/parser/main.py parser/lenta.ru parse
```

**Оба шага подряд:**
```bash
python3 parser/parser/main.py parser/lenta.ru all
```

## Формат результата

`parsed_articles.json` — список объектов:

```json
{
  "url": "https://lenta.ru/news/2024/01/15/headline/",
  "title": "Заголовок статьи",
  "description": "Краткое описание",
  "author": "Имя автора",
  "date_published": "2024-01-15T12:00:00",
  "section": "Россия",
  "body": "Полный текст статьи...",
  "body_length": 2800,
  "parsed_at": "2024-01-16T10:30:00"
}
```
