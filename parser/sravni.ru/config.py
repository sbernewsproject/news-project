"""
Настройки парсера для sravni.ru — отзывы о банках.

Запуск (из корня репозитория):
  python3 parser/parser/main.py parser/sravni.ru sitemap [--limit N]
  python3 parser/parser/main.py parser/sravni.ru parse   [--limit N]
  python3 parser/parser/main.py parser/sravni.ru all     [--limit N]

sitemap — обходит активные банки, собирает URL каждого отзыва → all_article_links.txt
          --limit N: обработать только первые N банков
parse   — для каждого URL отзыва загружает полный текст → parsed_articles.json
          --limit N: обработать только первые N отзывов

Формат записи совпадает с новостной статьёй:
  url, title, author, date_published, section ("bank_review"),
  bank_name, bank_slug, body, body_length, score, city, review_tag,
  product_name, problem_solved
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from parsers import collect_sravni_links, fetch_sravni_review

SITE_CONFIG = {
    "name": "Sravni.ru — Отзывы о банках",
    "url_prefix": "https://www.sravni.ru/bank/",

    # Переопределяем сбор ссылок: обходим страницы отзывов каждого банка
    "collect_links": collect_sravni_links,

    # Каждый отзыв парсится как отдельная статья
    "fetch_article": fetch_sravni_review,

    # Заглушки — не используются при наличии collect_links
    "sitemap_index":  "",
    "sitemap_filter": lambda u: False,
    "article_filter": lambda u: True,
}
