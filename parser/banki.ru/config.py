"""
Настройки парсера для banki.ru — раздел «Банки».

Запуск (из корня репозитория):
  python3 parser/parser/main.py parser/banki.ru sitemap
  python3 parser/parser/main.py parser/banki.ru parse --limit 5
  python3 parser/parser/main.py parser/banki.ru all --limit 10

sitemap — собирает slug'и банков из /sitemap/bankiru_banks_bank → all_article_links.txt
parse   — для каждого slug'а парсит карточку банка + первые 2 стр. отзывов → parsed_articles.json
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from parsers import collect_banki_links, fetch_banki_org

SITE_CONFIG = {
    "name": "Banki.ru — Банки",
    "url_prefix": "https://www.banki.ru/banks/bank/",

    # Переопределяем сбор ссылок: вместо XML sitemap — HTML-страница
    "collect_links": collect_banki_links,

    # Переопределяем парсинг: вместо статьи — карточка банка + отзывы
    "fetch_article": fetch_banki_org,

    # Заглушки — не используются при наличии collect_links,
    # но нужны чтобы load_site_config не упал при проверке
    "sitemap_index":  "",
    "sitemap_filter": lambda u: False,
    "article_filter": lambda u: True,
}
