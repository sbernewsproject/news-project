"""
Парсинг sravni.ru — отзывы о банках.

Использует прямой JSON API /proxy-reviews/reviews.
Все поля отзыва доступны в листинговом ответе — отдельные страницы не нужны.

Шаг sitemap собирает и сохраняет всё сразу:
  collect_sravni_links  →  all_article_links.txt + parsed_articles.json + parsing_progress.json

Шаг parse видит нулевой список и завершается мгновенно.
Функция fetch_sravni_review оставлена как запасной вариант.
"""

import json
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests
from bs4 import BeautifulSoup

BASE_URL  = "https://www.sravni.ru"
API_BASE  = "https://www.sravni.ru/proxy-reviews"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer":         "https://www.sravni.ru/",
}

SITEMAP_WORKERS  = 3    # банков параллельно
REQUEST_DELAY    = 0.3  # сек между API-запросами

_SESSION      = None
_SESSION_LOCK = threading.Lock()
_API_LOCK     = threading.Lock()  # не более 1 запроса к API за раз


def _session() -> requests.Session:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            s = requests.Session()
            s.headers.update(HEADERS)
            _SESSION = s
    return _SESSION


def _api_get(path: str, params: dict = None, retries: int = 3) -> requests.Response | None:
    """Запрос к JSON API. Сериализован через _API_LOCK + небольшая пауза."""
    global _SESSION
    url = API_BASE + path
    for attempt in range(1, retries + 1):
        net_error = None
        with _API_LOCK:
            time.sleep(REQUEST_DELAY)
            try:
                resp = _session().get(url, params=params, timeout=30)
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (404, 403):
                    return None
                print(f"  [!] HTTP {resp.status_code}: {url} (попытка {attempt})")
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                with _SESSION_LOCK:
                    _SESSION = None
                net_error = (type(e).__name__, 10 * attempt)
            except requests.RequestException as e:
                print(f"  [!] {e} (попытка {attempt})")
        if net_error:
            ename, wait = net_error
            print(f"  [!] {ename} (попытка {attempt}, пауза {wait}с)")
            time.sleep(wait)
    return None


def _html_get(path: str, retries: int = 3) -> requests.Response | None:
    """HTML-запрос только для получения списка банков."""
    global _SESSION
    url = BASE_URL + path
    for attempt in range(1, retries + 1):
        try:
            resp = _session().get(url, timeout=30)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (404, 403):
                return None
        except requests.RequestException as e:
            print(f"  [!] HTML {type(e).__name__}: {url} (попытка {attempt})")
            time.sleep(3)
    return None


def _extract_next_data(html_text: str) -> dict | None:
    soup = BeautifulSoup(html_text, "lxml")
    tag  = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return None
    try:
        return json.loads(tag.string)
    except (json.JSONDecodeError, ValueError):
        return None


# ── Преобразование API-объекта в запись отзыва ───────────────────────────────

def _item_to_review(item: dict, slug: str, bank_name: str) -> dict:
    review_id = item.get("id")
    url = f"{BASE_URL}/bank/{slug}/otzyvy/{review_id}/"

    author = " ".join(filter(None, [
        item.get("authorName", "") or "",
        item.get("authorLastName", "") or "",
    ]))

    city = ""
    loc  = item.get("locationData") or {}
    if loc:
        city = loc.get("name", "")

    body  = (item.get("text",  "") or "").replace("\xa0", " ").strip()
    title = (item.get("title", "") or "").replace("\xa0", " ").strip()

    return {
        "url":            url,
        "title":          title,
        "author":         author,
        "date_published": item.get("date", ""),
        "section":        "bank_review",
        "bank_name":      bank_name,
        "bank_slug":      slug,
        "body":           body,
        "body_length":    len(body),
        "score":          item.get("rating", ""),
        "city":           city,
        "review_tag":     item.get("reviewTag", ""),
        "product_name":   item.get("specificProductName", ""),
        "problem_solved": item.get("problemSolved", False),
    }


# ── Получение всех отзывов одного банка через API ────────────────────────────

def _fetch_bank_reviews(slug: str, bank_name: str, org_id: str) -> list[dict]:
    """Постранично обходит /proxy-reviews/reviews, возвращает список записей.

    API использует pageIndex (0-based): pageIndex=0 — первая страница.
    Параметр page игнорируется API — нужен именно pageIndex.
    """
    reviews   = []
    page      = 0
    seen_ids  = set()

    while True:
        params = {
            "reviewObjectId":   org_id,
            "reviewObjectType": "bank",
            "pageSize":         1000,
            "orderBy":          "byDate",
            "pageIndex":        page,
        }

        resp = _api_get("/reviews", params=params)
        if resp is None:
            break

        data      = resp.json()
        items     = data.get("items", [])
        total     = data.get("total", 0)
        page_size = data.get("pageSize", 1000)

        if not items:
            break

        new_items = 0
        for item in items:
            rid = item.get("id")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            reviews.append(_item_to_review(item, slug, bank_name))
            new_items += 1

        if new_items == 0:
            break

        max_pages = (total + page_size - 1) // page_size if page_size else 1
        if page >= max_pages - 1:
            break
        page += 1

    return reviews


# ── Шаг sitemap: сбор + сохранение всех отзывов ──────────────────────────────

def collect_sravni_links(cfg: dict, data_dir: str, limit: int = 0, fresh: bool = False, suffix: str = "") -> list[str]:
    """
    Получает все отзывы через API за один шаг.
    Сохраняет all_article_links.txt, parsed_articles.json, parsing_progress.json.
    После этого шаг parse не имеет незакрытых URL и завершается сразу.
    """
    links_file      = os.path.join(data_dir, f"all_article_links{suffix}.txt")
    results_path    = os.path.join(data_dir, f"parsed_articles{suffix}.json")
    progress_path   = os.path.join(data_dir, f"parsing_progress{suffix}.json")
    sitemap_prog    = os.path.join(data_dir, f"sitemap_progress{suffix}.json")

    print(f"sitemap: {cfg['name']}")

    banks_cache = os.path.join(data_dir, "banks.json")
    if os.path.exists(banks_cache):
        with open(banks_cache, encoding="utf-8") as f:
            banks = json.load(f)
        print(f"Список банков из кеша: {len(banks)} банков")
    else:
        print("Загружаю список банков...")
        resp = _html_get("/banki/otzyvy/")
        if resp is None:
            print("error: не удалось загрузить страницу банков")
            return []
        nd = _extract_next_data(resp.text)
        if nd is None:
            print("error: не найден __NEXT_DATA__ на странице банков")
            return []
        try:
            org_list = nd["props"]["initialReduxState"]["organizations"]["organizationsList"]
        except (KeyError, TypeError):
            print("error: не найден organizationsList")
            return []
        banks = [
            {"alias": o["alias"], "id": o["id"], "name": o.get("name", o["alias"])}
            for o in org_list
            if o.get("status") == "active" and o.get("alias") and o.get("id")
        ]
        os.makedirs(data_dir, exist_ok=True)
        with open(banks_cache, "w", encoding="utf-8") as f:
            json.dump(banks, f, ensure_ascii=False, indent=2)
        print(f"Список банков сохранён: {len(banks)} банков")

    slug_to_name = {b["alias"]: b["name"] for b in banks}
    slug_to_id   = {b["alias"]: b["id"]   for b in banks}
    all_slugs    = [b["alias"] for b in banks]
    print(f"Активных банков: {len(all_slugs)}")

    if limit:
        all_slugs = all_slugs[:limit]
        print(f"limit: {limit} банков")

    # Загружаем уже собранные данные (без --fresh — дополняем)
    if not fresh and os.path.exists(sitemap_prog):
        with open(sitemap_prog, encoding="utf-8") as f:
            sp = json.load(f)
        done_banks   = set(sp.get("processed_banks", []))
        all_articles = sp.get("articles", [])
        all_urls     = [a["url"] for a in all_articles]
        slugs        = [s for s in all_slugs if s not in done_banks]
        print(f"Уже обработано банков: {len(done_banks)}, осталось: {len(slugs)}")
        if not slugs:
            print("Все банки уже обработаны — используй --fresh чтобы начать заново")
            return all_urls
    else:
        done_banks   = set()
        all_articles = []
        all_urls     = []
        slugs        = all_slugs

    append_lock  = threading.Lock()
    total_banks  = len(slugs)
    done_count   = [0]
    bank_stats   = {}  # slug -> {"name": ..., "count": ...}

    def _process(args: tuple) -> None:
        i, slug = args
        bank_name = slug_to_name.get(slug, slug)
        org_id    = slug_to_id.get(slug, "")
        try:
            reviews = _fetch_bank_reviews(slug, bank_name, org_id)
        except Exception as e:
            print(f"[{i}/{total_banks}] {slug}: ошибка {e}")
            return

        now = datetime.now().isoformat()
        with append_lock:
            done_count[0] += 1
            done_banks.add(slug)
            bank_stats[slug] = {"name": bank_name, "count": len(reviews)}
            for rev in reviews:
                rev["parsed_at"] = now
                all_articles.append(rev)
                all_urls.append(rev["url"])
            print(f"[{done_count[0]}/{total_banks}] {bank_name}: +{len(reviews)} (итого {len(all_articles)})")
            _save_sitemap_progress(sitemap_prog, done_banks, all_articles, all_urls,
                                   results_path, progress_path, links_file)

    stats_path = os.path.join(data_dir, f"stats{suffix}.json")

    if total_banks:
        print(f"\nОбходим {total_banks} банков (workers={SITEMAP_WORKERS})...")
        run_started = datetime.now().isoformat()
        with ThreadPoolExecutor(max_workers=SITEMAP_WORKERS) as executor:
            list(executor.map(_process, enumerate(slugs, 1)))
        _save_sitemap_progress(sitemap_prog, done_banks, all_articles, all_urls,
                               results_path, progress_path, links_file)

        # Сводка по новым банкам этого прогона
        new_total = sum(v["count"] for v in bank_stats.values())
        print(f"\n{'─'*50}")
        print(f"Прогон завершён: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Обработано банков: {len(bank_stats)}")
        print(f"Новых отзывов:     {new_total}")
        print(f"Всего в базе:      {len(all_articles)}")
        if bank_stats:
            print(f"\nПо банкам (этот прогон):")
            for stat in sorted(bank_stats.values(), key=lambda x: x["count"], reverse=True):
                if stat["count"] > 0:
                    print(f"  {stat['name']}: {stat['count']}")
            zeros = [s["name"] for s in bank_stats.values() if s["count"] == 0]
            if zeros:
                print(f"  (без отзывов: {', '.join(zeros)})")
        print(f"{'─'*50}")

        # Обновляем stats.json для отчётности
        stats_data = {}
        if os.path.exists(stats_path):
            try:
                with open(stats_path, encoding="utf-8") as f:
                    stats_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                stats_data = {}
        runs = stats_data.get("runs", [])
        runs.append({
            "started_at":    run_started,
            "finished_at":   datetime.now().isoformat(),
            "fresh":         fresh,
            "banks_in_run":  len(bank_stats),
            "reviews_in_run": new_total,
            "total_in_db":   len(all_articles),
            "per_bank":      bank_stats,
        })
        stats_data["runs"] = runs
        stats_data["total_banks_done"] = len(done_banks)
        stats_data["total_reviews"]    = len(all_articles)
        stats_data["last_updated"]     = datetime.now().isoformat()
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats_data, f, ensure_ascii=False, indent=2)
        print(f"Статистика сохранена: {stats_path}")

    return all_urls


def _save_sitemap_progress(sitemap_prog, done_banks, all_articles, all_urls,
                            results_path, progress_path, links_file):
    os.makedirs(os.path.dirname(sitemap_prog), exist_ok=True)

    with open(sitemap_prog, "w", encoding="utf-8") as f:
        json.dump(
            {"processed_banks": list(done_banks), "articles": all_articles,
             "updated_at": datetime.now().isoformat()},
            f, ensure_ascii=False, indent=2,
        )
    with open(links_file, "w", encoding="utf-8") as f:
        f.write("\n".join(all_urls))
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(
            {"processed_urls": all_urls, "parsed_articles": all_articles,
             "total": len(all_articles), "updated_at": datetime.now().isoformat()},
            f, ensure_ascii=False, indent=2,
        )


# ── Запасной fetch: вызывается шагом parse для URL не из кеша ────────────────

def fetch_sravni_review(url: str) -> dict | None:
    """
    Используется шагом parse только если URL не был охвачен в sitemap.
    Получает один отзыв через API (поиск по банку + дате).
    """
    m = re.search(r"/bank/([^/]+)/otzyvy/(\d+)/", url)
    if not m:
        return {"error": "invalid review url"}
    slug, review_id_str = m.group(1), m.group(2)

    # Получить имя банка из одного запроса к API (первый отзыв банка)
    resp = _api_get("/reviews", params={
        "organizationAlias": slug,
        "reviewObjectType":  "bank",
        "pageSize":          1,
    })
    bank_name = slug
    if resp:
        data = resp.json()
        items = data.get("items", [])
        # bank name не приходит в item — оставляем slug как fallback

    # Ищем нужный отзыв по id среди свежих
    target_id = int(review_id_str)
    for page in range(1, 20):
        params = {
            "organizationAlias": slug,
            "reviewObjectType":  "bank",
            "pageSize":          1000,
            "orderBy":           "byDate",
        }
        if page > 1:
            params["page"] = page

        resp = _api_get("/reviews", params=params)
        if resp is None:
            break

        data  = resp.json()
        items = data.get("items", [])
        if not items:
            break

        for item in items:
            if item.get("id") == target_id:
                return _item_to_review(item, slug, bank_name)

        total     = data.get("total", 0)
        page_size = data.get("pageSize", 1000)
        max_pages = (total + page_size - 1) // page_size if page_size else 1
        if page >= max_pages:
            break

    return {"error": f"review {review_id_str} not found"}
