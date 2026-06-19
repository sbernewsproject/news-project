"""
Парсинг banki.ru — отзывы о банках.

Две публичные функции для config.py:
  collect_banki_links(cfg, data_dir, limit, fresh) → список URL отдельных отзывов
  fetch_banki_review(url)                          → dict в формате статьи (как новость)

Стратегия:
  - Sitemap-шаг: берём slug'и банков из /sitemap/bankiru_banks_bank,
    затем для каждого банка собираем URL отзывов со страниц листинга.
  - Parse-шаг: для каждого URL отзыва загружаем полный текст через JSON-LD.
"""

import html
import json
import os
import re
import time
import random

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.banki.ru"
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


# ── Сбор URL отзывов ─────────────────────────────────────────────────────────

def collect_banki_links(cfg: dict, data_dir: str, limit: int = 0, fresh: bool = False) -> list[str]:
    """
    Шаг 1: получает slug'и банков из /sitemap/bankiru_banks_bank.
    Шаг 2: для каждого банка обходит страницы листинга отзывов и собирает URL.
    limit — максимум банков для обхода (0 = все).
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

    resp = _get("/sitemap/bankiru_banks_bank")
    if resp is None:
        print("error: не удалось загрузить список банков")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    bank_pattern = re.compile(r"^/banks/bank/([^/]+)/$")
    seen_slugs = set()
    slugs = []
    for a in soup.find_all("a", href=bank_pattern):
        slug = bank_pattern.match(a["href"]).group(1)
        if slug not in seen_slugs:
            seen_slugs.add(slug)
            slugs.append(slug)

    print(f"Найдено банков: {len(slugs)}")
    if limit:
        slugs = slugs[:limit]
        print(f"limit: {limit} банков")

    review_urls = []
    seen_reviews = set()

    for i, slug in enumerate(slugs, 1):
        print(f"[{i}/{len(slugs)}] {slug}")
        for page in range(1, 20):
            rev_resp = _get(
                f"/services/responses/bank/{slug}/",
                params={"page": page} if page > 1 else None,
            )
            if rev_resp is None:
                break
            page_reviews = _parse_reviews_page(rev_resp.text, slug)
            if not page_reviews:
                break
            added = 0
            for r in page_reviews:
                rid = r.get("review_id")
                if rid and rid not in seen_reviews:
                    seen_reviews.add(rid)
                    review_urls.append(BASE_URL + r["review_url"])
                    added += 1
            print(f"  стр. {page}: +{added}")
            if len(page_reviews) < 5:
                break

    print(f"Найдено отзывов: {len(review_urls)}")

    os.makedirs(data_dir, exist_ok=True)
    with open(links_file, "w", encoding="utf-8") as f:
        f.write("\n".join(review_urls))
    with open(os.path.join(data_dir, "sitemap_progress.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"processed_sitemaps": slugs, "all_links": review_urls},
            f, ensure_ascii=False, indent=2,
        )

    print(f"done: {len(review_urls)} review URLs -> {links_file}")
    return review_urls


# ── Парсинг одного банка ──────────────────────────────────────────────────────

def fetch_banki_org(url: str) -> dict | None:
    """
    Для URL вида /banks/bank/{slug}/ собирает карточку банка
    и превью отзывов (первые 2 страницы).
    """
    m = re.search(r"/banks/bank/([^/]+)/", url)
    if not m:
        return {"error": "invalid url"}
    slug = m.group(1)

    resp = _get(f"/banks/bank/{slug}/")
    if resp is None:
        return {"error": "failed to load"}

    info = _parse_bank_card(slug, resp.text)

    # Отсеиваем ЖК/застройщиков (нет лицензии и нет ОГРН)
    if not info.get("license") and not info.get("ogrn"):
        return {"error": f"not a bank: {info.get('name', slug)}"}

    # Страница отзывов — агрегат (оценка, кол-во, % решённых) + превью отзывов
    reviews = []
    stats = {}
    for page in range(1, 3):
        rev_resp = _get(
            f"/services/responses/bank/{slug}/",
            params={"page": page} if page > 1 else None,
        )
        if rev_resp is None:
            break
        if page == 1:
            stats = _parse_reviews_stats(rev_resp.text)
        page_reviews = _parse_reviews_page(rev_resp.text, slug)
        if not page_reviews:
            break
        reviews.extend(page_reviews)

    return {
        "url":            url,
        "title":          info.get("name", slug),
        "date_published": "",
        "section":        "bank",
        **info,
        **stats,
        "reviews":          reviews,
        "reviews_fetched":  len(reviews),
    }


# ── Карточка банка ────────────────────────────────────────────────────────────

def _parse_bank_card(slug: str, html_text: str) -> dict:
    soup = BeautifulSoup(html_text, "lxml")
    info = {"slug": slug}

    # Название
    h1 = soup.find("h1")
    info["name"] = h1.get_text(strip=True) if h1 else ""

    # Блок с лицензией/ОГРН/годом — все в одном flexbox
    # Ищем строку "лицензия №" и берём весь родительский блок
    license_tag = soup.find(string=re.compile(r"лицензия №", re.I))
    if license_tag:
        block = license_tag.parent.parent  # flexbox
        raw = block.get_text(separator="|", strip=True)
        # "на рынке с|1991|года|лицензия №|1481|ОГРН|1027700132195|..."
        parts = [p.strip() for p in raw.split("|") if p.strip()]
        info["raw_license_block"] = raw  # сырые данные как есть

        for i, p in enumerate(parts):
            if "лицензия" in p.lower() and i + 1 < len(parts):
                info["license"] = parts[i + 1]
            if p.upper() == "ОГРН" and i + 1 < len(parts):
                info["ogrn"] = parts[i + 1]
            if "на рынке с" in p.lower() and i + 2 < len(parts):
                info["founded_year"] = parts[i + 1]

    # Народный рейтинг на карточке банка: "N место из M банков"
    for tag in soup.find_all(string=re.compile(r"\d+\s+место из \d+", re.I)):
        info["rating_place_raw"] = tag.strip()  # "34 место из 308 банков"
        break

    # Финансовый рейтинг
    for tag in soup.find_all(string=re.compile(r"^Финансовый рейтинг$", re.I)):
        block = tag.parent.parent
        texts = [t.strip() for t in block.stripped_strings]
        for t in texts:
            if "место" in t.lower():
                info["financial_rating_raw"] = t  # "1 место по России"
                break
        break

    # Продукты банка — только ссылки вида /products/{тип}/{slug}/
    # (не общие страницы типа /products/deposits/, не SEO-ссылки на чужие банки)
    product_pattern = re.compile(rf"^/products/[^/]+/{re.escape(slug)}/$")
    products = []
    seen_products = set()
    for a in soup.find_all("a", href=product_pattern):
        txt = a.get_text(strip=True)
        if txt and txt not in seen_products:
            seen_products.add(txt)
            products.append(txt)
    info["products"] = products

    return info


# ── Агрегированная статистика банка (со страницы отзывов) ────────────────────

def _parse_reviews_stats(html_text: str) -> dict:
    """
    Парсит агрегированные показатели банка с страницы отзывов:
    avg_score и reviews_total — из JSON-LD (@type: Organization),
    solved_pct и rating_place — из HTML.
    """
    soup = BeautifulSoup(html_text, "lxml")
    stats = {}

    # JSON-LD (@type: Organization) — самый надёжный источник оценки и кол-ва
    decoder = json.JSONDecoder(strict=False)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = decoder.decode(script.string or "")
            if isinstance(data, dict) and data.get("@type") == "Organization":
                agg = data.get("aggregateRating", {})
                stats["avg_score"]     = agg.get("ratingValue", "")
                stats["reviews_total"] = agg.get("reviewCount", "")
                break
        except (json.JSONDecodeError, ValueError, AttributeError):
            continue

    # % решённых проблем — блок "33.68%|решено проблем"
    for tag in soup.find_all(string=re.compile(r"решено проблем", re.I)):
        block = tag.parent.parent
        texts = [t.strip() for t in block.stripped_strings]
        if texts:
            stats["solved_pct"] = texts[0]  # "33.68%"
        break

    # Место в народном рейтинге — "34 место|из|308 банка"
    for tag in soup.find_all(string=re.compile(r"\d+\s*место", re.I)):
        stats["rating_place_raw"] = tag.strip()  # "34 место"
        # Ищем полный блок чтобы получить "из N банков"
        block = tag.parent.parent
        stats["rating_place_block"] = block.get_text(separator=" ", strip=True)
        break

    return stats


# ── Список отзывов ────────────────────────────────────────────────────────────

def _parse_reviews_page(html_text: str, slug: str) -> list[dict]:
    """
    Парсит страницу со списком отзывов.
    Якорь каждого отзыва: h3 > a[href*='/response/'] (стабильно).
    """
    soup = BeautifulSoup(html_text, "lxml")
    results = []

    # Находим все заголовки отзывов
    for h3 in soup.find_all("h3"):
        link = h3.find("a", href=re.compile(r"/response/\d+/"))
        if not link:
            continue

        r = {"org_slug": slug}

        # Ссылка и ID
        r["review_url"] = link["href"]
        rid_m = re.search(r"/response/(\d+)/", link["href"])
        r["review_id"] = rid_m.group(1) if rid_m else ""

        # Заголовок — сырой текст ссылки
        r["title"] = link.get_text(strip=True)

        # Ищем блок-контейнер отзыва (идём вверх от h3)
        container = h3
        for _ in range(8):
            container = container.parent
            if container is None:
                break
            if len(container.get_text(strip=True)) > 150:
                break

        if container is None:
            results.append(r)
            continue

        container_text = container.get_text(separator="\n", strip=True)

        # Оценка — число 1-5 после "Оценка:"
        score_m = re.search(r"Оценка:\s*\n?\s*([1-5])", container_text)
        r["score"] = score_m.group(1) if score_m else ""

        # Дата — первый паттерн DD.MM.YYYY HH:MM
        date_m = re.search(r"\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}", container_text)
        r["date"] = date_m.group(0) if date_m else ""

        # Краткий текст — второй a[href*="/response/"] в контейнере (не в h3)
        all_resp_links = container.find_all("a", href=re.compile(r"/response/\d+/"))
        preview_link = next(
            (a for a in all_resp_links if a.find_parent("h3") is None
             and a.get_text(strip=True)),
            None
        )
        r["text_preview"] = preview_link.get_text(strip=True) if preview_link else ""

        # Бейджи — ищем по тексту (стабильно, это реальный контент)
        BADGES = ["Зачтено", "Отзыв проверен", "Ответ банка", "Документы прикреплены", "Проблема решена"]
        found_badges = []
        for badge in BADGES:
            if badge.lower() in container_text.lower():
                found_badges.append(badge)
        r["badges"] = found_badges

        results.append(r)

    return results


# ── Полный отзыв ──────────────────────────────────────────────────────────────

def fetch_review_detail(category: str, review_id: str) -> dict | None:
    """
    Загружает полный текст отзыва.
    category: 'bank' | 'insurance' | 'mfo'
    """
    url_map = {
        "bank":      f"/services/responses/bank/response/{review_id}/",
        "insurance": f"/insurance/responses/company/response/{review_id}/",
        "mfo":       f"/microloans/responses/response/{review_id}/",
    }
    path = url_map.get(category)
    if not path:
        return None

    resp = _get(path)
    if resp is None:
        return None

    return _parse_review_detail(review_id, category, resp.text)


# ── Публичная функция для config.py ──────────────────────────────────────────

def fetch_banki_review(url: str) -> dict | None:
    """
    Загружает страницу одного отзыва и возвращает dict в формате статьи:
    url, title, author, date_published, section, body, body_length, score.
    """
    m = re.search(r"/response/(\d+)/", url)
    if not m:
        return {"error": "invalid review url"}
    review_id = m.group(1)

    if "/services/responses/bank/" in url:
        category = "bank"
    elif "/insurance/responses/" in url:
        category = "insurance"
    elif "/microloans/responses/" in url:
        category = "mfo"
    else:
        category = "bank"

    r = fetch_review_detail(category, review_id)
    if r is None:
        return {"error": "failed to load"}

    raw = r.get("text_full", "")
    if not raw:
        return {"error": "empty review body"}

    text = BeautifulSoup(raw, "lxml").get_text(separator="\n", strip=True)

    return {
        "url":            url,
        "title":          r.get("title", ""),
        "author":         r.get("author_id", ""),
        "date_published": r.get("date", ""),
        "section":        "bank_review",
        "bank_name":      r.get("bank_name", ""),
        "body":           text,
        "body_length":    len(text),
        "score":          r.get("score", ""),
    }


def _parse_review_detail(review_id: str, category: str, html_text: str) -> dict:
    soup = BeautifulSoup(html_text, "lxml")
    r = {"review_id": review_id, "category": category}

    # JSON-LD — самый надёжный источник структурированных данных.
    # strict=False нужен потому что banki.ru кладёт литеральные \n внутрь строк reviewBody.
    _decoder = json.JSONDecoder(strict=False)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = _decoder.decode(script.string or "")
            if not isinstance(data, dict):
                continue
            if data.get("@type") == "Review":
                r["title"]     = data.get("name", "")
                r["score"]     = data.get("reviewRating", {}).get("ratingValue", "")
                r["author_id"] = data.get("author", {}).get("name", "")
                body_raw       = data.get("author", {}).get("reviewBody", "")
                r["text_full"] = html.unescape(body_raw)
                r["bank_name"] = data.get("itemReviewed", {}).get("name", "")
                break
        except (json.JSONDecodeError, ValueError, AttributeError):
            continue

    # Заголовок — fallback к h1 если нет в JSON-LD
    if not r.get("title"):
        h1 = soup.find("h1")
        r["title"] = h1.get_text(strip=True) if h1 else ""

    # Дата публикации — первый span/div с датой DD.MM.YYYY
    date_m = re.search(r"\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2})?", soup.get_text())
    r["date"] = date_m.group(0) if date_m else ""

    # Автор + город — структура: outer_div > span.author_wrap > span > "user-XXX"
    #                                          > span.city → "Город"
    for tag in soup.find_all(string=re.compile(r"user-\d+")):
        if tag.parent and tag.parent.name == "span":
            outer_div = tag.parent.parent.parent  # inner_span → mid_span → outer_div
            top_spans = outer_div.find_all("span", recursive=False)
            # top_spans[0] = mid_span с автором, top_spans[1] = span с городом
            if len(top_spans) >= 2:
                r["city"] = top_spans[1].get_text(strip=True)
            if not r.get("author_id"):
                r["author_id"] = tag.strip()
            break

    # Теги/категории — div.text-size-6 (стабильный класс дизайн-системы)
    r["tags"] = [
        div.get_text(strip=True)
        for div in soup.find_all("div", class_="text-size-6")
        if div.get_text(strip=True)
    ]

    # Бейджи статуса
    full_text = soup.get_text()
    BADGES = ["Зачтено", "Отзыв проверен", "Ответ банка", "Документы прикреплены", "Проблема решена"]
    r["badges"] = [b for b in BADGES if b.lower() in full_text.lower()]

    return r
