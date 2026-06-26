# sravni.ru — Отзывы о банках

Парсер отзывов с sravni.ru. Каждый отзыв сохраняется как отдельная запись.

## Как работает (важно — архитектура изменилась)

Парсер использует прямой JSON API сайта (`/proxy-reviews/reviews`) вместо HTML-страниц.

**Шаг `sitemap` делает всё за один проход:**
1. Загружает список активных банков (~275 штук) с `/banki/otzyvy/` — 1 HTML-запрос
2. Для каждого банка вызывает JSON API с `pageSize=1000` — получает все отзывы сразу
3. Сохраняет готовые отзывы в `parsed_articles.json` и `parsing_progress.json`

**Шаг `parse` — мгновенный no-op:** все URL уже в `processed_urls`, очередь пустая, парсер выходит сразу.

Для sravni.ru достаточно запускать только `sitemap`.

## Команды

Все команды выполняются из корня репозитория.

```bash
# Полный сбор всех отзывов (все ~275 активных банков)
python3 parser/parser/main.py parser/sravni.ru sitemap

# Тест — первые 5 банков
python3 parser/parser/main.py parser/sravni.ru sitemap --limit 5

# Начать заново (сбросить кеш)
python3 parser/parser/main.py parser/sravni.ru sitemap --fresh

# all — то же что sitemap (parse завершится мгновенно)
python3 parser/parser/main.py parser/sravni.ru all --limit 5

# Запуск параллельно со старым (отдельные файлы)
python3 parser/parser/main.py parser/sravni.ru sitemap --suffix _new
```

**Флаги:**

| Флаг | Применяется к | Что делает |
|------|--------------|------------|
| `--limit N` | `sitemap` | Обходит только первые N банков |
| `--fresh` | `sitemap` | Игнорирует кеш, пересобирает |
| `--suffix X` | `sitemap`, `parse` | Добавляет `X` к именам файлов (`parsed_articles_X.json`) |

> `--limit` на шаге `parse` не имеет смысла — parse всегда видит пустую очередь.

## Источники данных

| Шаг | Метод | URL |
|-----|-------|-----|
| Список банков | HTML + `__NEXT_DATA__` | `https://www.sravni.ru/banki/otzyvy/` |
| Отзывы банка | **JSON API** | `https://www.sravni.ru/proxy-reviews/reviews` |

**Параметры API:**
- `reviewObjectId={id}` — MongoDB ObjectId банка из `organizationsList.id`
- `reviewObjectType=bank` — только банковские отзывы
- `pageSize=1000` — максимально возможный размер страницы
- `orderBy=byDate` — хронологический порядок

> `organizationAlias` в этом API игнорируется — фильтрация только по `reviewObjectId`.

## Формат результата

`parsed_articles.json` — список объектов, по одному на отзыв:

```json
{
  "url": "https://www.sravni.ru/bank/sberbank-rossii/otzyvy/1126129/",
  "title": "Мошенничество сбербанка с кредитными картами",
  "author": "Дарья Арутюнова",
  "date_published": "2026-05-10T08:22:13.577071Z",
  "section": "bank_review",
  "bank_name": "Сбербанк",
  "bank_slug": "sberbank-rossii",
  "body": "Здравствуйте, имею негативный опыт...",
  "body_length": 969,
  "score": 1,
  "city": "Армавир",
  "review_tag": "creditCards",
  "product_name": "СберКарта",
  "problem_solved": false,
  "parsed_at": "2026-06-23T10:00:00"
}
```

### Описание полей

| Поле | Тип | Описание |
|------|-----|----------|
| `url` | str | Прямая ссылка на отзыв |
| `title` | str | Заголовок отзыва |
| `author` | str | Имя автора (`"Пользователь"` для анонимных) |
| `date_published` | str | Дата публикации ISO 8601 |
| `section` | str | Всегда `"bank_review"` |
| `bank_name` | str | Название банка |
| `bank_slug` | str | Slug банка (из URL) |
| `body` | str | Полный текст отзыва (plain text) |
| `body_length` | int | Длина текста в символах |
| `score` | int | Оценка 1–5 |
| `city` | str | Город автора (или пустая строка) |
| `review_tag` | str | Категория отзыва (см. ниже) |
| `product_name` | str\|null | Конкретный продукт банка, если указан |
| `problem_solved` | bool | Отмечено ли, что проблема решена |
| `parsed_at` | str | Время парсинга |

### Значения `review_tag`

| Тег | Смысл |
|-----|-------|
| `serviceLevel` | Уровень обслуживания |
| `credits` | Кредиты |
| `creditCards` | Кредитные карты |
| `savings` | Вклады и счета |
| `remoteService` | Дистанционное обслуживание |
| `creditRefinancing` | Рефинансирование |
| `mortgage` | Ипотека |
| `moneyOrder` | Денежные переводы |

## Известные особенности

- `--limit N` на `sitemap` ограничивает количество **банков**, не отзывов.
- Банки без отзывов в API дают `+0` и пропускаются.
- Прогресс внутри обхода одного банка не сохраняется — если прервать, нужен `--fresh`.
- `score` — число 1–5 или пустая строка если оценки нет.
