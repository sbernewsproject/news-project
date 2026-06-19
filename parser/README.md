# SBERparser

Парсер новостных сайтов. Работает в два шага: сначала собирает ссылки через sitemap,
потом загружает и парсит каждую статью.

Каждый сайт — отдельная папка со своим `config.py`. Ядро (`parser/`) общее.

## Структура

```
parser/           ядро (не трогать)
  main.py                   точка входа
  sitemap.py                сбор ссылок
  article.py                парсинг статей

komsomolskaya_pravda/
  config.py                 настройки парсера для kp.ru
  all_article_links.txt     ссылки (шаг 1)
  parsed_articles.json      результат (шаг 2)
  parsing_progress.json     прогресс парсинга
  sitemap_progress.json     прогресс сбора ссылок

lenta.ru/
  config.py
  ...
```

## Установка

Создать виртуальное окружение:
```bash
python3 -m venv .venv_parser
```

Активировать:
```bash
source .venv_parser/bin/activate
```

Установить зависимости:
```bash
pip3 install requests
```

## Запуск

```bash
python3 parser/main.py <папка> <команда> [--limit N]
```

**Команды:**

| Команда   | Что делает                         |
|-----------|------------------------------------|
| `sitemap` | собирает ссылки на статьи          |
| `parse`   | парсит статьи по собранным ссылкам |
| `all`     | оба шага подряд                    |

**Флаг `--limit N`** ограничивает количество:
- для `sitemap` — N sub-sitemap'ов
- для `parse` — N статей

**Флаг `--fresh`** игнорирует сохранённый прогресс и начинает с начала.
Удобно при повторном тестировании одних и тех же статей.

## Команды по сайтам

### Комсомольская Правда

```bash
# тест
python3 parser/main.py komsomolskaya_pravda sitemap --limit 2
python3 parser/main.py komsomolskaya_pravda parse --limit 5
python3 parser/main.py komsomolskaya_pravda parse --limit 5 --fresh

# полный прогон
python3 parser/main.py komsomolskaya_pravda sitemap
python3 parser/main.py komsomolskaya_pravda parse
python3 parser/main.py komsomolskaya_pravda all
```

### Lenta.ru

```bash
# тест
python3 parser/main.py lenta.ru sitemap --limit 2
python3 parser/main.py lenta.ru parse --limit 5
python3 parser/main.py lenta.ru parse --limit 5 --fresh

# полный прогон
python3 parser/main.py lenta.ru sitemap
python3 parser/main.py lenta.ru parse
python3 parser/main.py lenta.ru all
```

Прогресс сохраняется после каждой статьи — можно прервать и продолжить.

## Формат результата

`parsed_articles.json` — список объектов:

```json
[
  {
    "url": "https://www.kp.ru/daily/...",
    "title": "Заголовок",
    "description": "Краткое описание",
    "author": "Имя автора",
    "date_published": "2024-01-15T12:00:00+03:00",
    "section": "Политика",
    "body": "Полный текст...",
    "body_length": 3200,
    "parsed_at": "2024-01-16T10:30:00"
  }
]
```

## Добавить новый сайт

Создать папку и `config.py` в ней:

```python
SITE_CONFIG = {
    "name": "РИА Новости",
    "sitemap_index": "https://ria.ru/sitemap_index.xml",
    "sitemap_gzip": False,
    "sitemap_filter": lambda url: "ria.ru/sitemap_" in url,
    "article_filter": lambda url: "/2024" in url or "/2025" in url,
    "url_prefix": "https://ria.ru/",
}
```

```bash
python3 parser/main.py ria.ru sitemap --limit 2   # проверить
python3 parser/main.py ria.ru all                  # полный прогон
```
