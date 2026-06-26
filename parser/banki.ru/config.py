"""
Настройки парсера для banki.ru — отзывы о банках.

Запуск (из корня репозитория):
  python3 parser/parser/main.py parser/banki.ru sitemap [--limit N] [--fresh]

sitemap делает всё: через AJAX JSON API получает все отзывы по всем банкам,
сохраняет в parsed_articles.json и помечает все URL как обработанные.
Шаг parse завершается мгновенно ("nothing to parse").

  --limit N: обработать только первые N банков
  --fresh:   сбросить прогресс и начать заново
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from parsers import collect_banki_links

SITE_CONFIG = {
    "name": "Banki.ru — Отзывы",
    "url_prefix": "https://www.banki.ru/services/responses/bank/response/",

    # Переопределяем сбор: вместо XML sitemap — AJAX JSON API
    "collect_links": collect_banki_links,

    # fetch_article не нужен — sitemap собирает полные отзывы сразу
    # Заглушки — не используются при наличии collect_links
    "sitemap_index":  "",
    "sitemap_filter": lambda u: False,
    "article_filter": lambda u: True,
}
