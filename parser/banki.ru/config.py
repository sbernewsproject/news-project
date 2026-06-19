"""
Настройки парсера для banki.ru — отзывы о банках.

Запуск (из корня репозитория):
  python3 parser/parser/main.py parser/banki.ru sitemap [--limit N]
  python3 parser/parser/main.py parser/banki.ru parse   [--limit N]
  python3 parser/parser/main.py parser/banki.ru all     [--limit N]

sitemap — обходит банки, собирает URL каждого отзыва → all_article_links.txt
          --limit N: обработать только первые N банков
parse   — для каждого URL отзыва загружает полный текст → parsed_articles.json
          --limit N: обработать только первые N отзывов

Формат записи совпадает с новостной статьёй:
  url, title, author, date_published, section ("bank_review"), body, body_length, score
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from parsers import collect_banki_links, fetch_banki_review

SITE_CONFIG = {
    "name": "Banki.ru — Отзывы",
    "url_prefix": "https://www.banki.ru/services/responses/bank/response/",

    # Переопределяем сбор ссылок: вместо XML sitemap — HTML-обход страниц отзывов
    "collect_links": collect_banki_links,

    # Каждый отзыв парсится как отдельная статья в формате новости
    "fetch_article": fetch_banki_review,

    # Заглушки — не используются при наличии collect_links
    "sitemap_index":  "",
    "sitemap_filter": lambda u: False,
    "article_filter": lambda u: True,
}
