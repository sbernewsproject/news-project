# banki.ru — Отзывы о банках

Парсер отзывов с banki.ru. Каждый отзыв сохраняется как отдельная запись.

## Как работает

Шаг `sitemap` делает всё: использует **AJAX JSON API** (`/services/responses/list/ajax/`) вместо парсинга HTML. Тот же эндпоинт, что браузер вызывает при нажатии «Показать ещё». Возвращает чистый JSON с 25 отзывами на странице и флагом `hasMorePages`.

| Шаг | URL | Что берём |
|-----|-----|-----------|
| Список банков | `/sitemap/bankiru_banks_bank` | slug и имя (~359 банков) |
| Отзывы | `/services/responses/list/ajax/?page=N&bank={slug}&is_countable=on` | JSON: title, text (HTML), grade, dateCreate |

### Сравнение с HTML-подходом

| | HTML-парсинг | AJAX API |
|---|---|---|
| Формат | JSON-LD в HTML-странице (948 КБ) | Чистый JSON (300 КБ) |
| BeautifulSoup | для текста отзывов | только для зачистки HTML-тегов из поля `text` |
| Пагинация | вычислять max_pages из JSON-LD | `hasMorePages: bool` |
| Нагрузка на канал | 3× больше | baseline |

## Запуск

Все команды выполняются из корня репозитория.

**Тест — первые N банков:**
```bash
python3 parser/parser/main.py parser/banki.ru sitemap --limit 5
```

**Полный прогон (все ~359 банков):**
```bash
python3 parser/parser/main.py parser/banki.ru sitemap
```

**Начать заново (сбросить весь кеш):**
```bash
python3 parser/parser/main.py parser/banki.ru sitemap --fresh
```

**Продолжить после прерывания** (без `--fresh` — дополняет, не трогает уже собранные банки):
```bash
python3 parser/parser/main.py parser/banki.ru sitemap
```

**С суффиксом** (изолированный набор файлов):
```bash
python3 parser/parser/main.py parser/banki.ru sitemap --suffix _test --limit 10
```

## Кеш и прогресс

| Файл | Описание |
|------|----------|
| `banks.json` | Список банков (slug + имя). Используется повторно без `--fresh`. |
| `sitemap_progress{suffix}.json` | Какие банки уже обработаны. Используется для resume. |
| `parsed_articles{suffix}.json` | Все отзывы. |
| `all_article_links{suffix}.txt` | URL всех отзывов. |
| `stats{suffix}.json` | История прогонов: сколько банков, отзывов, по банкам. |

## Формат результата

`parsed_articles.json` — список объектов, по одному на отзыв:

```json
{
  "url": "https://www.banki.ru/services/responses/bank/response/13174555/",
  "title": "Ужасное отношение к клиентам",
  "author": "puser-22045676088",
  "date_published": "2026-06-22 11:58:34",
  "section": "bank_review",
  "bank_name": "Сбербанк",
  "bank_slug": "sberbank",
  "body": "Текст отзыва без HTML-тегов...",
  "body_length": 412,
  "score": "5",
  "parsed_at": "2026-06-23T10:52:19"
}
```

## Особенности

- `--limit N` на шаге `sitemap` ограничивает количество **банков**, не отзывов.
- `score` — строка от `"1"` до `"5"`.
- Поле `text` в API содержит HTML-теги (`<p>`, `<br>`). Парсер очищает их через BeautifulSoup.
- `pageSize` параметр API игнорирует — всегда 25 отзывов на страницу.

## Ограничения и блокировки

banki.ru блокирует IP при слишком частых запросах. Блокировка снимается через ~30 минут.

Чтобы избежать блокировки, парсер:
- Использует `cloudscraper` (имитирует Chrome, обходит Cloudflare)
- Делает warmup-запрос к главной странице при старте (получает сессионные куки)
- Выжидает 3–6 секунд между запросами
- Отправляет заголовок `X-Requested-With: XMLHttpRequest`
- Работает строго в 1 поток

**Примерное время полного прогона:** зависит от количества отзывов.
При 3–6с на запрос и ~40 страницах на крупный банк — крупные банки (Сбербанк: ~4900 стр.) займут несколько часов.

> Никогда не запускай отдельные тестовые скрипты параллельно с парсером — это удваивает частоту запросов и гарантированно приводит к бану.

## Зависимости

```bash
pip3 install requests beautifulsoup4 lxml cloudscraper
```
