"""
Lenta.ru News Parser
====================

Pipeline:
  RSS / Sitemap / Архив  →  список URL
    └─► fetch_article(url)  →  полный текст, картинка, автор, дата
          └─► save_json()   →  news.json

Эндпоинты:
  RSS      : https://lenta.ru/rss          ← 200 свежих новостей (основной)
  Sitemap  : https://lenta.ru/news/sitemap.xml.gz  ← архив URL (без мета)
  Архив дня: https://lenta.ru/YYYY/MM/DD/  ← все материалы за день
  Статья   : https://lenta.ru/news/YYYY/MM/DD/<slug>/
  Статья   : https://lenta.ru/articles/YYYY/MM/DD/<slug>/

Примечание по sitemap: lenta.ru не публикует Google News Sitemap с тегами
news:title/news:keywords. Доступный sitemap содержит архивные URL без мета.
"""

import gzip
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from html.parser import HTMLParser

import requests as _req

# ──────────────────────────────────────────────────────────
# Константы
# ──────────────────────────────────────────────────────────

SITEMAP_URL = "https://lenta.ru/news/sitemap.xml.gz"
RSS_URL     = "https://lenta.ru/rss"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ──────────────────────────────────────────────────────────
# Низкоуровневые утилиты
# ──────────────────────────────────────────────────────────

def fetch(url: str, retries: int = 3, delay: float = 1.5) -> bytes:
    """HTTP GET с повторами через requests. Возвращает bytes или b'' при ошибке."""
    for attempt in range(1, retries + 1):
        try:
            r = _req.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return r.content
        except _req.exceptions.HTTPError as e:
            print(f"  [HTTP {e.response.status_code}] {url}  (попытка {attempt}/{retries})")
        except _req.exceptions.RequestException as e:
            print(f"  [Error] {e}  (попытка {attempt}/{retries})")
        if attempt < retries:
            time.sleep(delay)
    return b""


def save_json(data: list, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {path}  ({len(data)} записей)")


def load_json(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_rfc2822(s: str) -> str:
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).isoformat()
    except Exception:
        return s

# ──────────────────────────────────────────────────────────
# ШАГ 1 — Источники URL
# ──────────────────────────────────────────────────────────

def fetch_sitemap_urls(url: str = SITEMAP_URL) -> list[dict]:
    """
    Загружает sitemap.xml.gz и возвращает список URL:
      [{ url, published_at }, ...]

    Примечание: lenta.ru не предоставляет Google News Sitemap с заголовками.
    Sitemap содержит архивные URL, метаданные будут получены со страниц статей.
    """
    print(f"\n[SITEMAP] {url}")
    raw = fetch(url)
    if not raw:
        return []

    try:
        xml_bytes = gzip.decompress(raw)
    except Exception:
        xml_bytes = raw

    root = ET.fromstring(xml_bytes)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    results = []
    skipped = 0
    for url_el in root.findall("sm:url", ns):
        loc     = url_el.findtext("sm:loc",     namespaces=ns, default="")
        lastmod = url_el.findtext("sm:lastmod", namespaces=ns, default="")

        # Пропускаем партнёрские ссылки и не-новостные разделы
        if "/extlink/" in loc or not loc:
            skipped += 1
            continue
        if not re.search(r"/(?:news|articles)/\d{4}/\d{2}/\d{2}/", loc):
            skipped += 1
            continue

        results.append({
            "url":          loc,
            "title":        "",
            "published_at": lastmod,
            "keywords":     [],
        })

    print(f"  Найдено: {len(results)} новостей  (пропущено: {skipped})")
    return results


def fetch_archive_urls(day: date) -> list[dict]:
    """
    Резервный источник URL — страница архива за конкретный день.
    https://lenta.ru/YYYY/MM/DD/
    Возвращает [{ url, title, date }]
    """
    page_url = f"https://lenta.ru/{day.strftime('%Y/%m/%d')}/"
    print(f"\n[АРХИВ] {page_url}")
    raw = fetch(page_url)
    if not raw:
        return []

    html = raw.decode("utf-8", errors="replace")

    pattern = r'href="(/(?:news|articles)/\d{4}/\d{2}/\d{2}/[^"]+/)"[^>]*>([^<]+)'
    seen, results = set(), []
    for m in re.finditer(pattern, html):
        href, title = m.group(1), m.group(2).strip()
        url = "https://lenta.ru" + href
        if url not in seen and title:
            seen.add(url)
            results.append({"url": url, "title": title, "date": day.isoformat()})

    print(f"  Найдено: {len(results)} материалов за {day}")
    return results


def fetch_rss_urls() -> list[dict]:
    """
    Основной источник URL — RSS фид (200 свежих новостей).
    Даёт: title, description, image_url, category, author, published_at.
    """
    print(f"\n[RSS] {RSS_URL}")
    raw = fetch(RSS_URL)
    if not raw:
        return []

    root = ET.fromstring(raw)
    channel = root.find("channel")
    if channel is None:
        return []

    results = []
    for item in channel.findall("item"):
        def tag(name: str) -> str:
            el = item.find(name)
            return el.text.strip() if el is not None and el.text else ""

        # lenta.ru использует <enclosure url="..."> для картинок, не media:content
        img = ""
        enc = item.find("enclosure")
        if enc is not None:
            img = enc.get("url", "")

        url = tag("link") or tag("guid")
        if not url or "/extlink/" in url:
            continue

        results.append({
            "url":          url,
            "title":        tag("title"),
            "published_at": _parse_rfc2822(tag("pubDate")),
            "description":  _strip_html(tag("description")),
            "image_url":    img,
            "category":     tag("category"),
            "author":       tag("author"),
        })

    print(f"  Найдено: {len(results)} новостей")
    return results


# ──────────────────────────────────────────────────────────
# ШАГ 2 — Парсинг полного текста статьи
# ──────────────────────────────────────────────────────────

class _ArticleParser(HTMLParser):
    """Извлекает заголовок и тело из HTML страницы lenta.ru."""

    def __init__(self):
        super().__init__()
        self.title      = ""
        self.image_url  = ""
        self.text_parts = []
        self._in_h1     = False
        self._in_body   = False
        self._in_p      = False
        self._in_author = False
        self.author     = ""
        self._buf       = ""
        self._depth     = 0
        self._body_depth = 0

    def handle_starttag(self, tag, attrs):
        d  = dict(attrs)
        cl = d.get("class", "")

        if tag == "h1":
            self._in_h1 = True
            self._buf   = ""

        elif tag == "img" and not self.image_url:
            src = d.get("src", "")
            if "icdn.lenta.ru" in src and "owl_detail" in src:
                self.image_url = src

        elif tag in ("div", "article", "section") and not self._in_body:
            if any(k in cl for k in ("topic-body", "b-text", "article__text", "news-block")):
                self._in_body    = True
                self._body_depth = self._depth

        # Автор: <span class="topic-authors__name">
        elif tag == "span" and "topic-authors__name" in cl:
            self._in_author = True
            self._buf       = ""

        if self._in_body and tag == "p":
            self._in_p = True
            self._buf  = ""

        self._depth += 1

    def handle_data(self, data):
        if self._in_h1 or self._in_author:
            self._buf += data
        elif self._in_p and self._in_body:
            self._buf += data

    def handle_endtag(self, tag):
        self._depth -= 1

        if tag == "h1" and self._in_h1:
            self.title  = self._buf.strip()
            self._in_h1 = False

        elif tag == "span" and self._in_author:
            self.author    = self._buf.strip()
            self._in_author = False

        elif self._in_body and tag == "p" and self._in_p:
            t = self._buf.strip()
            # Пропускаем подписи к фото/кадру ("Фото: ТАСС", "Кадр: ВКонтакте" и т.д.)
            if t and not t.startswith(("Фото:", "Кадр:", "Иллюстрация:")):
                self.text_parts.append(t)
            self._in_p = False
            self._buf  = ""

        elif self._in_body and tag in ("div", "article", "section"):
            if self._depth <= self._body_depth:
                self._in_body = False


def _extract_og(html: str) -> dict:
    """Парсим og:* мета-теги и категорию из <title>."""
    result = {}
    for m in re.finditer(
        r'<meta[^>]+(?:property|name)=["\']og:(\w+)["\'][^>]+content=["\']([^"\']*)["\']',
        html, re.I
    ):
        result[f"og:{m.group(1)}"] = m.group(2)
    for m in re.finditer(
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']og:(\w+)["\']',
        html, re.I
    ):
        result[f"og:{m.group(2)}"] = m.group(1)
    # Категория из <title>: "Заголовок : Рубрика : Lenta.ru"
    tm = re.search(r"<title>([^<]+)</title>", html, re.I)
    if tm:
        parts = [p.strip() for p in tm.group(1).split(":")]
        if len(parts) >= 3:
            result["category"] = parts[-2]
    return result


def _extract_jsonld(html: str) -> dict:
    """Извлекает datePublished и author из JSON-LD (самый надёжный источник дат)."""
    match = re.search(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
        if isinstance(data, list):
            data = next((d for d in data if d.get("@type") == "NewsArticle"), {})
        result = {}
        if data.get("datePublished"):
            result["published_at"] = data["datePublished"]
        author = data.get("author", {})
        if isinstance(author, dict) and author.get("name"):
            result["author"] = author["name"]
        elif isinstance(author, list) and author:
            result["author"] = author[0].get("name", "")
        return result
    except Exception:
        return {}


def fetch_article(url: str, pause: float = 0.7) -> dict:
    """
    Загружает страницу новости и возвращает полный объект:
      url, title, published_at, author, description,
      image_url, category, body (текст абзацами через \\n\\n)
    """
    time.sleep(pause)
    raw = fetch(url)
    if not raw:
        return {"url": url, "error": "fetch failed"}

    html = raw.decode("utf-8", errors="replace")
    og   = _extract_og(html)
    ld   = _extract_jsonld(html)

    p = _ArticleParser()
    p.feed(html)

    body = "\n\n".join(p.text_parts).strip() or None

    return {
        "url":          url,
        "title":        p.title                         or og.get("og:title", ""),
        "published_at": ld.get("published_at", ""),
        "author":       p.author                        or ld.get("author", ""),
        "description":  og.get("og:description", ""),
        "image_url":    p.image_url                     or og.get("og:image", ""),
        "category":     og.get("category", ""),
        "body":         body,
    }


def parse_html(url: str, html: str) -> dict:
    """Parse article from pre-downloaded HTML string (no HTTP — for async pipeline)."""
    og   = _extract_og(html)
    ld   = _extract_jsonld(html)
    p    = _ArticleParser()
    p.feed(html)
    body = "\n\n".join(p.text_parts).strip() or None
    return {
        "url":          url,
        "title":        p.title        or og.get("og:title", ""),
        "published_at": ld.get("published_at", ""),
        "author":       p.author       or ld.get("author", ""),
        "description":  og.get("og:description", ""),
        "image_url":    p.image_url    or og.get("og:image", ""),
        "category":     og.get("category", ""),
        "body":         body,
    }


# ──────────────────────────────────────────────────────────
# ШАГ 3 — Pipeline: источник → полный текст → JSON
# ──────────────────────────────────────────────────────────

def run_pipeline(
    source:      str  = "rss",
    days_back:   int  = 1,
    limit:       int  = 0,
    fetch_body:  bool = True,
    output:      str  = "news.json",
    dedupe_file: str  = "seen_urls.json",
) -> list[dict]:
    """
    Полный pipeline:
      1. Получаем список URL из выбранного источника
      2. Фильтруем уже виденные URL (дедупликация)
      3. Для каждого URL загружаем полный текст статьи
      4. Сохраняем в JSON

    Args:
        source:      "rss" | "sitemap" | "archive"
        days_back:   для source="archive" — сколько дней брать
        limit:       максимум статей (0 = все)
        fetch_body:  если False — только мета, без тела статьи
        output:      итоговый JSON файл
        dedupe_file: файл с уже обработанными URL
    """
    # ── 1. Получаем список URL ──────────────────────────────
    if source == "rss":
        items = fetch_rss_urls()
    elif source == "sitemap":
        items = fetch_sitemap_urls()
    elif source == "archive":
        items = []
        today = date.today()
        for i in range(days_back):
            items.extend(fetch_archive_urls(today - timedelta(days=i)))
    else:
        raise ValueError(f"Неизвестный source: {source!r}")

    if not items:
        print("  Нет данных для обработки.")
        return []

    # ── 2. Дедупликация ────────────────────────────────────
    seen = set(load_json(dedupe_file)) if dedupe_file else set()
    new_items = [it for it in items if it["url"] not in seen]
    print(f"\n  Всего: {len(items)}  |  Новых: {len(new_items)}  |  Уже видели: {len(seen)}")

    if limit > 0:
        new_items = new_items[:limit]
        print(f"  Лимит применён: {limit} статей")

    if not new_items:
        print("  Нечего обрабатывать — все URL уже видели.")
        return []

    # ── 3. Загружаем полный текст ──────────────────────────
    results = []
    total   = len(new_items)
    for i, item in enumerate(new_items, 1):
        slug = item["url"].split("lenta.ru")[-1].rstrip("/")
        print(f"  [{i:3}/{total}] {slug}")

        if fetch_body:
            article = fetch_article(item["url"])
            # Мержим мета из источника с данными страницы
            merged = {**item, **{k: v for k, v in article.items() if v}}
            results.append(merged)
        else:
            results.append(item)

    # ── 4. Сохраняем ──────────────────────────────────────
    existing = load_json(output)
    all_data = existing + results
    save_json(all_data, output)

    if dedupe_file:
        all_seen = list(seen | {it["url"] for it in results})
        with open(dedupe_file, "w", encoding="utf-8") as f:
            json.dump(all_seen, f, ensure_ascii=False)
        print(f"  ✓ seen_urls: {len(all_seen)} URL сохранено")

    return results


# ──────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────

def _usage():
    print("""
Использование:
  python parser.py rss [--limit N] [--no-body] [--out FILE]
      Основной режим: RSS (200 свежих) → полный текст → news.json

  python parser.py archive [--days N] [--limit N] [--no-body] [--out FILE]
      Архив за N дней → полный текст → news.json

  python parser.py sitemap [--limit N] [--no-body] [--out FILE]
      Sitemap (архивные URL) → полный текст → news.json

Примеры:
  python parser.py rss
  python parser.py rss --limit 20 --out today.json
  python parser.py archive --days 3
  python parser.py rss --no-body
""")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        _usage()
        sys.exit(0)

    mode = args[0]
    if mode not in ("rss", "sitemap", "archive"):
        _usage()
        sys.exit(1)

    limit    = 0
    days     = 1
    no_body  = False
    out_file = "news.json"

    i = 1
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        elif args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1]); i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out_file = args[i + 1]; i += 2
        elif args[i] == "--no-body":
            no_body = True; i += 1
        else:
            i += 1

    run_pipeline(
        source     = mode,
        days_back  = days,
        limit      = limit,
        fetch_body = not no_body,
        output     = out_file,
    )
