"""
Парсинг sravni.ru — отзывы о банках.

Две публичные функции для config.py:
  collect_sravni_links(cfg, data_dir, limit, fresh) → список URL отдельных отзывов
  fetch_sravni_review(url)                          → dict в формате статьи (как новость)

Стратегия:
  - Slug-шаг: берём slug'и банков из __NEXT_DATA__ главной страницы /banki/otzyvy/.
              Фильтр: status == 'active' (≈275 банков).
  - Страничный обход: для каждого банка запрашиваем /bank/{slug}/otzyvy/?page={N},
    извлекаем id отзывов из __NEXT_DATA__ и формируем URL отдельного отзыва.
  - Parse-шаг: загружаем страницу отзыва, достаём данные из __NEXT_DATA__.
"""

import json
import os
import re
import time
import random

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.sravni.ru"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
    "Connection": "keep-alive",
}

_SESSION = None


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update(HEADERS)
    return _SESSION


def _get(path: str, params: dict = None, retries: int = 3) -> requests.Response | None:
    url = BASE_URL + path
    for attempt in range(1, retries + 1):
        time.sleep(random.uniform(1.5, 3.5))
        try:
            resp = _session().get(url, params=params, timeout=20)
            if resp.status_code == 200:
                return resp
            print(f"  [!] HTTP {resp.status_code}: {url} (попытка {attempt})")
            if resp.status_code in (403, 404):
                break
        except requests.RequestException as e:
            print(f"  [!] Ошибка: {e} (попытка {attempt})")
    return None


def _extract_next_data(html_text: str) -> dict | None:
    """Извлекает объект __NEXT_DATA__ из HTML-страницы Next.js."""
    soup = BeautifulSoup(html_text, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return None
    try:
        return json.loads(tag.string)
    except (json.JSONDecodeError, ValueError):
        return None


# ── Сбор URL отзывов ─────────────────────────────────────────────────────────

def collect_sravni_links(cfg: dict, data_dir: str, limit: int = 0, fresh: bool = False) -> list[str]:
    """
    Шаг 1: получает slug'и банков с главной страницы /banki/otzyvy/.
    Шаг 2: для каждого банка обходит страницы отзывов и собирает URL.
    limit — максимум банков для обхода (0 = все active).
    Сохраняет URL отзывов в all_article_links.txt.
    """
    links_file = os.path.join(data_dir, "all_article_links.txt")

    if not fresh and os.path.exists(links_file):
        with open(links_file, encoding="utf-8") as f:
            existing = [l.strip() for l in f if l.strip()]
        if existing:
            print(f"sitemap: {cfg['name']}")
            print(f"progress: {len(existing)} URL отзывов уже сохранено")
            return existing

    print(f"sitemap: {cfg['name']}")
    print("Загружаю список банков...")

    resp = _get("/banki/otzyvy/")
    if resp is None:
        print("error: не удалось загрузить главную страницу отзывов")
        return []

    nd = _extract_next_data(resp.text)
    if nd is None:
        print("error: не найден __NEXT_DATA__ на главной странице")
        return []

    try:
        redux = nd["props"]["initialReduxState"]
        org_list = redux["organizations"]["organizationsList"]
    except (KeyError, TypeError):
        print("error: не найден organizationsList в __NEXT_DATA__")
        return []

    slugs = [o["alias"] for o in org_list if o.get("status") == "active" and o.get("alias")]
    print(f"Найдено активных банков: {len(slugs)}")

    if limit:
        slugs = slugs[:limit]
        print(f"limit: {limit} банков")

    review_urls = []
    seen_ids = set()

    for i, slug in enumerate(slugs, 1):
        print(f"[{i}/{len(slugs)}] {slug}")
        for page in range(1, 500):
            params: dict = {"page": page} if page > 1 else {}
            # byDate гарантирует полный обход без пропусков (byPopularity может дать 0 на 2-й стр.)
            params["orderBy"] = "byDate"
            rev_resp = _get(f"/bank/{slug}/otzyvy/", params=params)
            if rev_resp is None:
                break

            nd_page = _extract_next_data(rev_resp.text)
            if nd_page is None:
                break

            try:
                items = nd_page["props"]["initialReduxState"]["reviews"]["list"]["items"]
                total = nd_page["props"]["initialReduxState"]["reviews"]["list"].get("total", 0)
                page_size = nd_page["props"]["initialReduxState"]["reviews"]["list"].get("pageSize", 10)
            except (KeyError, TypeError):
                break

            if not items:
                break

            added = 0
            for item in items:
                rid = item.get("id")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    review_urls.append(f"{BASE_URL}/bank/{slug}/otzyvy/{rid}/")
                    added += 1

            print(f"  стр. {page}: +{added} (всего в банке: {total})")

            # Прекращаем если собрали все отзывы банка
            max_pages = (total + page_size - 1) // page_size if page_size else 1
            if page >= max_pages or added == 0:
                break

    print(f"Найдено отзывов: {len(review_urls)}")

    os.makedirs(data_dir, exist_ok=True)
    with open(links_file, "w", encoding="utf-8") as f:
        f.write("\n".join(review_urls))
    with open(os.path.join(data_dir, "sitemap_progress.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"processed_banks": slugs, "all_links": review_urls},
            f, ensure_ascii=False, indent=2,
        )

    print(f"done: {len(review_urls)} review URLs -> {links_file}")
    return review_urls


# ── Полный отзыв ──────────────────────────────────────────────────────────────

def fetch_sravni_review(url: str) -> dict | None:
    """
    Загружает страницу одного отзыва и возвращает dict в формате статьи:
    url, title, author, date_published, section, bank_name, body, body_length,
    score, city, review_tag, product_name, problem_solved.
    """
    # Извлекаем slug и id из URL /bank/{slug}/otzyvy/{id}/
    m = re.search(r"/bank/([^/]+)/otzyvy/(\d+)/", url)
    if not m:
        return {"error": "invalid review url"}
    slug, review_id = m.group(1), m.group(2)

    # Определяем путь
    resp = _get(f"/bank/{slug}/otzyvy/{review_id}/")
    if resp is None:
        return {"error": "failed to load"}

    nd = _extract_next_data(resp.text)
    if nd is None:
        return {"error": "no __NEXT_DATA__"}

    try:
        item = nd["props"]["initialReduxState"]["reviews"]["review"]["item"]
    except (KeyError, TypeError):
        return {"error": "no review item in __NEXT_DATA__"}

    if not item:
        return {"error": "review item is null"}

    text_raw = item.get("text", "")
    if not text_raw:
        return {"error": "empty review body"}

    # На детальной странице text — уже plain text, но проверяем на HTML
    if text_raw.strip().startswith("<"):
        body = BeautifulSoup(text_raw, "lxml").get_text(separator="\n", strip=True)
    else:
        body = text_raw.strip()
    body = body.replace("\xa0", " ")

    author_name = " ".join(filter(None, [
        item.get("authorName", ""),
        item.get("authorLastName", ""),
    ]))

    city = ""
    loc = item.get("locationData") or {}
    if loc:
        city = loc.get("name", "")

    return {
        "url":              url,
        "title":            (item.get("title", "") or "").replace("\xa0", " "),
        "author":           author_name,
        "date_published":   item.get("date", ""),
        "section":          "bank_review",
        "bank_name":        item.get("organizationName", ""),
        "bank_slug":        slug,
        "body":             body,
        "body_length":      len(body),
        "score":            item.get("rating", ""),
        "city":             city,
        "review_tag":       item.get("reviewTag", ""),
        "product_name":     item.get("specificProductName", ""),
        "problem_solved":   item.get("problemSolved", False),
    }
