"""
Парсинг banki.ru — отзывы о банках.

Использует AJAX JSON API: /services/responses/list/ajax/?page=N&bank={slug}&is_countable=on
Возвращает JSON с 25 отзывами на странице + флаг hasMorePages.
Намного быстрее парсинга HTML — нет BeautifulSoup, ответ в 3x меньше.

Шаг sitemap собирает и сохраняет всё сразу:
  collect_banki_links → all_article_links.txt + parsed_articles.json + parsing_progress.json

Шаг parse видит нулевой список и завершается мгновенно.
"""

import html as html_lib
import json
import os
import random
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import cloudscraper
import requests
from bs4 import BeautifulSoup

BASE_URL        = "https://www.banki.ru"
AJAX_PATH       = "/services/responses/list/ajax/"
PAGE_SIZE       = 25   # фиксировано на banki.ru
SITEMAP_WORKERS = 1    # один банк за раз — banki.ru агрессивно блокирует параллельные запросы
DELAY_MIN       = 3.0  # минимальная пауза между запросами (сек)
DELAY_MAX       = 6.0  # максимальная пауза

_SESSION      = None
_SESSION_LOCK = threading.Lock()
_API_LOCK     = threading.Lock()  # не более 1 запроса за раз


def _session() -> cloudscraper.CloudScraper:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            s = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
            s.headers.update({
                "Accept-Language": "ru-RU,ru;q=0.9",
                "Accept":          "application/json, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer":         "https://www.banki.ru/services/responses/bank/",
            })
            # Warmup: получаем сессионные куки
            try:
                s.get(BASE_URL + "/", timeout=20)
            except Exception:
                pass
            _SESSION = s
    return _SESSION


def _get(params: dict, retries: int = 3):
    """GET /services/responses/list/ajax/ с заданными params."""
    global _SESSION
    url = BASE_URL + AJAX_PATH
    for attempt in range(1, retries + 1):
        net_error = None
        with _API_LOCK:
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            try:
                resp = _session().get(url, params=params, timeout=30)
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (403, 404):
                    return None
                print(f"  [!] HTTP {resp.status_code}: {url}?{params} (попытка {attempt})")
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                with _SESSION_LOCK:
                    _SESSION = None
                net_error = (type(e).__name__, 60 * attempt)
            except Exception as e:
                print(f"  [!] {e} (попытка {attempt})")
        if net_error:
            ename, wait = net_error
            print(f"  [!] {ename} (попытка {attempt}, пауза {wait}с) — возможна блокировка IP")
            time.sleep(wait)
    return None


# ── Преобразование JSON-ответа API в запись ─────────────────────────────────

def _strip_html(text: str) -> str:
    """Убирает HTML-теги из текста отзыва."""
    if not text:
        return ""
    return BeautifulSoup(html_lib.unescape(text), "lxml").get_text("\n", strip=True)


def _item_to_review(item: dict, bank_slug: str, bank_name: str) -> dict:
    """Преобразует объект из AJAX API в стандартную запись отзыва."""
    review_id = item.get("id", "")
    url = f"{BASE_URL}/services/responses/bank/response/{review_id}/" if review_id else ""
    body = _strip_html(item.get("text", ""))
    return {
        "url":            url,
        "title":          (item.get("title", "") or "").strip(),
        "author":         item.get("userName", ""),
        "date_published": item.get("dateCreate", ""),
        "section":        "bank_review",
        "bank_name":      bank_name,
        "bank_slug":      bank_slug,
        "body":           body,
        "body_length":    len(body),
        "score":          str(item.get("grade", "")),
    }


# ── Получение всех отзывов одного банка ─────────────────────────────────────

def _fetch_bank_reviews(slug: str, bank_name: str) -> list[dict]:
    """
    Пагинирует AJAX JSON API для одного банка.
    Останавливается когда hasMorePages=False или данные закончились.
    """
    reviews = []
    page    = 1

    while True:
        params = {
            "page":         page,
            "is_countable": "on",
            "bank":         slug,
        }
        resp = _get(params)
        if resp is None:
            break

        try:
            data = resp.json()
        except Exception:
            break

        items = data.get("data", [])
        if not items:
            break

        for item in items:
            reviews.append(_item_to_review(item, slug, bank_name))

        if not data.get("hasMorePages", False):
            break

        page += 1

    return reviews


# ── Шаг sitemap: сбор + сохранение всех отзывов ─────────────────────────────

def collect_banki_links(cfg: dict, data_dir: str, limit: int = 0, fresh: bool = False, suffix: str = "") -> list[str]:
    links_file    = os.path.join(data_dir, f"all_article_links{suffix}.txt")
    results_path  = os.path.join(data_dir, f"parsed_articles{suffix}.json")
    progress_path = os.path.join(data_dir, f"parsing_progress{suffix}.json")
    sitemap_prog  = os.path.join(data_dir, f"sitemap_progress{suffix}.json")

    print(f"sitemap: {cfg['name']}")

    banks_cache = os.path.join(data_dir, "banks.json")
    if os.path.exists(banks_cache):
        with open(banks_cache, encoding="utf-8") as f:
            banks = json.load(f)
        print(f"Список банков из кеша: {len(banks)} банков")
    else:
        print("Загружаю список банков...")
        # Для получения списка банков нужно загрузить один HTML-запрос
        s = _session()
        s.headers.update({"Accept": "text/html,application/xhtml+xml"})
        resp = s.get(BASE_URL + "/sitemap/bankiru_banks_bank", timeout=20)
        s.headers.update({"Accept": "application/json, */*"})
        if resp is None or resp.status_code != 200:
            print("error: не удалось загрузить список банков")
            return []
        soup    = BeautifulSoup(resp.text, "lxml")
        pattern = re.compile(r"^/banks/bank/([^/]+)/$")
        seen, banks = set(), []
        for a in soup.find_all("a", href=pattern):
            slug = pattern.match(a["href"]).group(1)
            raw_name = a.get_text(strip=True) or slug
            name     = raw_name.split(" в ")[0].strip() or slug
            if slug not in seen:
                seen.add(slug)
                banks.append({"slug": slug, "name": name})
        os.makedirs(data_dir, exist_ok=True)
        with open(banks_cache, "w", encoding="utf-8") as f:
            json.dump(banks, f, ensure_ascii=False, indent=2)
        print(f"Список банков сохранён: {len(banks)} банков")

    slug_to_name = {b["slug"]: b["name"] for b in banks}
    all_slugs    = [b["slug"] for b in banks]
    print(f"Активных банков: {len(all_slugs)}")

    if limit:
        all_slugs = all_slugs[:limit]
        print(f"limit: {limit} банков")

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

    append_lock = threading.Lock()
    total_banks = len(slugs)
    done_count  = [0]
    bank_stats  = {}

    def _process(args: tuple) -> None:
        i, slug = args
        bank_name = slug_to_name.get(slug, slug)
        try:
            reviews = _fetch_bank_reviews(slug, bank_name)
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

        stats_data = {}
        if os.path.exists(stats_path):
            try:
                with open(stats_path, encoding="utf-8") as f:
                    stats_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                stats_data = {}
        runs = stats_data.get("runs", [])
        runs.append({
            "started_at":     run_started,
            "finished_at":    datetime.now().isoformat(),
            "fresh":          fresh,
            "banks_in_run":   len(bank_stats),
            "reviews_in_run": new_total,
            "total_in_db":    len(all_articles),
            "per_bank":       bank_stats,
        })
        stats_data["runs"]             = runs
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


# ── Запасной fetch для шага parse ────────────────────────────────────────────

def fetch_banki_review(url: str) -> dict | None:
    """Запасной метод: загружает один отзыв по URL (для шага parse)."""
    m = re.search(r"/response/(\d+)/", url)
    if not m:
        return {"error": "invalid review url"}
    review_id = m.group(1)

    params = {"page": 1, "is_countable": "on"}
    # Попытка найти через API не реализована — возвращаем заглушку
    return {"error": "use sitemap step to collect all reviews"}
