"""
Универсальный парсер статей через JSON-LD.

Работает для любого сайта, который публикует разметку NewsArticle
в теге <script type="application/ld+json">.
"""

import json
import re
import threading

import requests

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}

_SESSION      = None
_SESSION_LOCK = threading.Lock()


def _session() -> requests.Session:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            s = requests.Session()
            s.headers.update(HEADERS)
            _SESSION = s
    return _SESSION


def fetch_article(url: str) -> dict | None:
    """
    Загружает страницу и извлекает данные статьи из JSON-LD.
    Возвращает dict или None если статья не найдена/не подходит.
    """
    try:
        r = _session().get(url, timeout=15)
        r.raise_for_status()
    except Exception:
        return None

    match = re.search(
        r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
        r.text, re.DOTALL
    )
    if not match:
        return None

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    # Поддерживаем как одиночный объект, так и массив
    if isinstance(data, list):
        data = next((d for d in data if d.get("@type") == "NewsArticle"), None)
    if not data or data.get("@type") != "NewsArticle":
        return None

    author = ""
    raw_author = data.get("author", {})
    if isinstance(raw_author, list) and raw_author:
        author = raw_author[0].get("name", "")
    elif isinstance(raw_author, dict):
        author = raw_author.get("name", "")

    body = data.get("articleBody", "")
    return {
        "url":            url,
        "title":          data.get("headline", ""),
        "description":    data.get("description", ""),
        "author":         author or "Неизвестен",
        "date_published": data.get("datePublished", ""),
        "section":        data.get("articleSection", ""),
        "body":           body,
        "body_length":    len(body),
    }


def parse_html(url: str, html: str) -> dict | None:
    """Extract article from pre-downloaded HTML (used by async pipeline)."""
    match = re.search(
        r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    if not match:
        return None

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    if isinstance(data, list):
        data = next((d for d in data if d.get("@type") == "NewsArticle"), None)
    if not data or data.get("@type") != "NewsArticle":
        return None

    author = ""
    raw_author = data.get("author", {})
    if isinstance(raw_author, list) and raw_author:
        author = raw_author[0].get("name", "")
    elif isinstance(raw_author, dict):
        author = raw_author.get("name", "")

    body = data.get("articleBody", "")
    return {
        "url":            url,
        "title":          data.get("headline", ""),
        "description":    data.get("description", ""),
        "author":         author or "Неизвестен",
        "date_published": data.get("datePublished", ""),
        "section":        data.get("articleSection", ""),
        "body":           body,
        "body_length":    len(body),
    }
