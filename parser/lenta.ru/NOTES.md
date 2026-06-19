# Заметки по парсингу lenta.ru

## Почему config.py импортирует parser.py

Универсальный парсер (`parser/article.py`) извлекает данные статьи через JSON-LD —
структурированную разметку в теге `<script type="application/ld+json">`.
Это работает для большинства сайтов, включая kp.ru.

У lenta.ru в JSON-LD поле `articleBody` пустое — сайт туда текст не кладёт.
Текст статьи находится в HTML внутри `<div class="topic-body">`.

В `parser.py` написан HTML-парсер (`_ArticleParser`), который вытаскивает текст
напрямую из разметки. Поэтому `config.py` импортирует `fetch_article` из `parser.py`
и передаёт её в `SITE_CONFIG["fetch_article"]` — ядро парсера увидит эту функцию
и использует её вместо дефолтной.

## Источники данных

| Поле          | Источник                        |
|---------------|---------------------------------|
| title         | `<h1>` на странице              |
| author        | `<span class="topic-authors__name">` |
| date_published| JSON-LD `datePublished`         |
| description   | OG-тег `og:description`         |
| section       | `<title>` страницы (третья часть после `:`) |
| body          | `<p>` внутри `.topic-body`      |
