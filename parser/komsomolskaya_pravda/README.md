# Комсомольская Правда

## Как работает

Стандартный двухшаговый парсер: сначала собирает ссылки через XML sitemap, потом парсит каждую статью.

| Шаг | Что делает |
|-----|-----------|
| `sitemap` | Обходит XML sitemap (`kp.ru/sitemap.xml`) и собирает ссылки на статьи |
| `parse` | Загружает страницу каждой статьи и извлекает данные из JSON-LD |

Скорость парсинга: **~35 статей/сек** (100 async-соединений, без задержки).

## Запуск

Все команды выполняются из корня репозитория.

**Тест — 2 sitemap'а:**
```bash
python3 parser/parser/main.py parser/komsomolskaya_pravda sitemap --limit 2
```

**Полный сбор ссылок:**
```bash
python3 parser/parser/main.py parser/komsomolskaya_pravda sitemap
```

**Тест парсинга — 5 статей:**
```bash
python3 parser/parser/main.py parser/komsomolskaya_pravda parse --limit 5
```

**Повторить те же 5 (игнорировать прогресс):**
```bash
python3 parser/parser/main.py parser/komsomolskaya_pravda parse --limit 5 --fresh
```

**Полный парсинг:**
```bash
python3 parser/parser/main.py parser/komsomolskaya_pravda parse
```

**Оба шага подряд:**
```bash
python3 parser/parser/main.py parser/komsomolskaya_pravda all
```

## Формат результата

`parsed_articles.json` — список объектов:

```json
{
  "url": "https://www.kp.ru/daily/...",
  "title": "Заголовок статьи",
  "description": "Краткое описание",
  "author": "Имя автора",
  "date_published": "2024-01-15T12:00:00+03:00",
  "section": "Политика",
  "body": "Полный текст статьи...",
  "body_length": 3200,
  "parsed_at": "2024-01-16T10:30:00"
}
```
