# sravni.ru — Отзывы о банках

Парсер отзывов с sravni.ru. Каждый отзыв сохраняется как отдельная запись в формате новостной статьи.

## Запуск

Все команды выполняются из корня репозитория.

**Собрать URL отзывов (все активные банки):**
```bash
python3 parser/parser/main.py parser/sravni.ru sitemap
```

**Собрать URL отзывов (тест — первые N банков):**
```bash
python3 parser/parser/main.py parser/sravni.ru sitemap --limit 5
```

**Спарсить отзывы (тест — первые N отзывов):**
```bash
python3 parser/parser/main.py parser/sravni.ru parse --limit 20
```

**Полный прогон:**
```bash
python3 parser/parser/main.py parser/sravni.ru all
```

**Начать заново (игнорировать кеш):**
```bash
python3 parser/parser/main.py parser/sravni.ru sitemap --fresh
python3 parser/parser/main.py parser/sravni.ru parse --fresh
```

## Источники данных

| Шаг | URL | Что берём |
|-----|-----|-----------|
| Список банков | `/banki/otzyvy/` | slug'и активных банков (~275 штук) из `__NEXT_DATA__` |
| Листинг отзывов | `/bank/{slug}/otzyvy/?orderBy=byDate&page={N}` | ID отзывов из `__NEXT_DATA__` (все страницы) |
| Полный отзыв | `/bank/{slug}/otzyvy/{id}/` | все поля отзыва из `__NEXT_DATA__` |

Сайт построен на Next.js — данные берутся из встроенного в HTML блока `__NEXT_DATA__` (SSR), без обращения к отдельному API.

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
  "parsed_at": "2026-06-22T12:00:00"
}
```

### Описание полей

| Поле | Тип | Описание |
|------|-----|----------|
| `url` | str | Прямая ссылка на отзыв |
| `title` | str | Заголовок отзыва |
| `author` | str | Имя автора (или `"Анонимный Пользователь"`) |
| `date_published` | str | Дата публикации в ISO 8601 |
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

## Известные особенности

- `--limit` на шаге `sitemap` ограничивает количество банков, а не отзывов.
- `--limit` на шаге `parse` ограничивает количество отзывов.
- Банки без отзывов пропускаются автоматически на шаге `sitemap`.
- Обход идёт по сортировке `byDate`, чтобы не пропускать отзывы (сортировка по популярности может возвращать 0 элементов на последней неполной странице).
- `score` — целое число от 1 до 5.
