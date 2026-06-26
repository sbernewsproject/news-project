"""
Настройки парсера для Lenta.ru.
"""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from parser import fetch_article as _fetch_article_lenta
from parser import parse_html as _parse_html_lenta


def _fetch_article_wrapper(url: str) -> dict | None:
    """Оборачивает fetch_article из parser.py в формат, ожидаемый ядром."""
    result = _fetch_article_lenta(url, pause=0)
    if "error" in result:
        return result
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


def _parse_html_wrapper(url: str, html: str) -> dict | None:
    """Оборачивает parse_html из parser.py в формат ядра (для async pipeline)."""
    result = _parse_html_lenta(url, html)
    body = result.get("body") or ""
    if not body:
        return None
    return {
        "url":            result.get("url", url),
        "title":          result.get("title", ""),
        "description":    result.get("description", ""),
        "author":         result.get("author", ""),
        "date_published": result.get("published_at", ""),
        "section":        result.get("category", ""),
        "body":           body,
        "body_length":    len(body),
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
    "fetch_article": _fetch_article_wrapper,  # sync fallback (не используется при наличии parse_html)
    "parse_html":    _parse_html_wrapper,     # async path
    "parse_workers": 100,
}
