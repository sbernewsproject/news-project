# Parser

Универсальный парсер. Работает в два шага: сначала собирает список URL,
потом загружает и парсит каждую страницу.

Каждый источник — отдельная папка со своим `config.py`. Ядро (`parser/`) общее.

## Источники

| Папка | Тип данных | Метод сбора URL |
|-------|-----------|----------------|
| `komsomolskaya_pravda/` | Новостные статьи | XML sitemap |
| `lenta.ru/` | Новостные статьи | XML sitemap |
| `banki.ru/` | Карточки банков + отзывы | HTML-страница со списком |

## Структура

```
parser/                     ядро (не трогать)
  main.py                   точка входа
  sitemap.py                сбор ссылок через XML sitemap
  article.py                парсинг статей через JSON-LD

komsomolskaya_pravda/       настройки для kp.ru
  config.py
  all_article_links.txt     ссылки (шаг 1)
  parsed_articles.json      результат (шаг 2)
  parsing_progress.json     прогресс
  sitemap_progress.json

lenta.ru/                   настройки для lenta.ru
  config.py
  parser.py                 кастомный парсер статей

banki.ru/                   настройки для banki.ru
  config.py
  parsers.py                парсинг карточек банков и отзывов
  README.md                 подробная документация
```

## Установка

```bash
python3 -m venv .venv_parser
source .venv_parser/bin/activate
pip3 install requests beautifulsoup4 lxml
```

## Запуск

```bash
python3 parser/parser/main.py <папка> <команда> [--limit N] [--fresh]
```

**Команды:**

| Команда   | Что делает                         |
|-----------|------------------------------------|
| `sitemap` | собирает ссылки на статьи          |
| `parse`   | парсит статьи по собранным ссылкам |
| `all`     | оба шага подряд                    |

**Флаг `--limit N`** ограничивает количество:
- для `sitemap` — N sub-sitemap'ов
- для `parse` — N статей/банков

**Флаг `--fresh`** игнорирует сохранённый прогресс и начинает сначала.
Удобно при повторном тестировании тех же URL.

## Команды по сайтам

### Комсомольская Правда

```bash
# тест
python3 parser/parser/main.py parser/komsomolskaya_pravda sitemap --limit 2
python3 parser/parser/main.py parser/komsomolskaya_pravda parse --limit 5
python3 parser/parser/main.py parser/komsomolskaya_pravda parse --limit 5 --fresh

# полный прогон
python3 parser/parser/main.py parser/komsomolskaya_pravda all
```
Подробнее: [komsomolskaya_pravda/README.md](komsomolskaya_pravda/README.md)

### Lenta.ru

```bash
# тест
python3 parser/parser/main.py parser/lenta.ru sitemap --limit 2
python3 parser/parser/main.py parser/lenta.ru parse --limit 5

# полный прогон
python3 parser/parser/main.py parser/lenta.ru all
```
Подробнее: [lenta.ru/README.md](lenta.ru/README.md)

### Banki.ru — Банки

```bash
# собрать список банков (~360 штук)
python3 parser/parser/main.py parser/banki.ru sitemap

# тест — 5 банков
python3 parser/parser/main.py parser/banki.ru parse --limit 5

# повторить те же 5 банков
python3 parser/parser/main.py parser/banki.ru parse --limit 5 --fresh

# полный прогон (оба шага подряд)
python3 parser/parser/main.py parser/banki.ru all
```

Подробнее: [banki.ru/README.md](banki.ru/README.md)

Прогресс сохраняется после каждой записи — можно прервать и продолжить.

## Формат результата

### Новостные сайты (kp.ru, lenta.ru)

`parsed_articles.json` — список объектов:

```json
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
```

### Banki.ru

`parsed_articles.json` — список объектов, по одному на банк. Каждый содержит карточку банка и массив `reviews` с превью отзывов. Подробнее в [banki.ru/README.md](banki.ru/README.md).

## Добавить новый сайт

Создать папку и `config.py` в ней с `SITE_CONFIG`.

**Для сайтов с XML sitemap:**
```python
SITE_CONFIG = {
    "name": "РИА Новости",
    "sitemap_index": "https://ria.ru/sitemap_index.xml",
    "sitemap_filter": lambda url: "ria.ru/sitemap_" in url,
    "article_filter": lambda url: "/2024" in url,
    "url_prefix": "https://ria.ru/",
}
```

**Для сайтов без XML sitemap** — добавить ключ `collect_links` с функцией `(cfg, data_dir, limit, fresh) -> list[str]`.
Ядро вызовет её вместо стандартного XML-парсера. Пример: `banki.ru/config.py`.
