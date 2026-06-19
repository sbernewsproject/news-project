"""
Настройки парсера для Lenta.ru.
"""

import re
import sys
import os

# Подключаем кастомный парсер статей из этой же папки
sys.path.insert(0, os.path.dirname(__file__))
from parser import fetch_article


def _fetch_article_wrapper(url: str) -> dict | None:
    """Оборачивает fetch_article из parser.py в формат, ожидаемый ядром."""
    result = fetch_article(url, pause=0)
    if "error" in result:
        return result
    # Приводим к общему формату
    return {
        "url":            result.get("url", url),
        "title":          result.get("title", ""),
        "description":    result.get("description", ""),
        "author":         result.get("author", ""),
        "date_published": result.get("published_at", ""),
        "section":        result.get("category", ""),
        "body":           result.get("body") or "",
        "body_length":    len(result.get("body") or ""),
    }


SITE_CONFIG = {
    "name": "Lenta.ru",
    "sitemap_index": "https://lenta.ru/sitemap.xml.gz",
    "sitemap_gzip": True,
    "sitemap_filter": lambda url: "lenta.ru/news/sitemap" in url,
    "article_filter": lambda url: (
        bool(re.search(r"/(?:news|articles)/\d{4}/\d{2}/\d{2}/[^/]+/", url))
        and "/extlink/" not in url
    ),
    "url_prefix": "https://lenta.ru/",
    "fetch_article": _fetch_article_wrapper,
}
