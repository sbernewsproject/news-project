"""
Парсинг news.mail.ru — новости.
Использует sitemap: /sitemap/ -> /sitemap/YYYY-month/ -> /sitemap/YYYY-month/D/
Каждый день содержит список ссылок на статьи.
Шаг sitemap собирает все ссылки и сразу парсит каждую статью, сохраняя в parsed_articles.json.
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

BASE_URL = "https://news.mail.ru"
SITEMAP_WORKERS = 1  # один запрос за раз — mail.ru агрессивно блокирует параллельные запросы
DELAY_MIN = 2.0  # минимальная пауза между запросами (сек)
DELAY_MAX = 4.0  # максимальная пауза

_SESSION = None
_SESSION_LOCK = threading.Lock()
_API_LOCK = threading.Lock()  # не более 1 запроса за раз


def _session() -> cloudscraper.CloudScraper:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            s = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
            s.headers.update({
                "Accept-Language": "ru-RU,ru;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            })
            # Warmup: получаем сессионные куки
            try:
                s.get(BASE_URL + "/", timeout=20)
            except Exception:
                pass
            _SESSION = s
        return _SESSION


def _get(url: str, retries: int = 3):
    """GET запрос с повторами."""
    global _SESSION
    for attempt in range(1, retries + 1):
        net_error = None
        with _API_LOCK:
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            try:
                resp = _session().get(url, timeout=30)
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (403, 404):
                    return None
                print(f"  [!] HTTP {resp.status_code}: {url} (попытка {attempt})")
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


def _parse_article(url: str) -> dict | None:
    """Парсит одну статью по URL."""
    resp = _get(url)
    if resp is None:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # Title
    h1 = soup.find(attrs={"itemprop": "headline"})
    title = h1.get_text(strip=True) if h1 else ""

    # Date
    time_tag = soup.find("time")
    date_published = time_tag.get("datetime", "") if time_tag else ""

    # Author
    author_meta = soup.find("meta", property="author")
    author = author_meta.get("content", "") if author_meta else ""

    # Source
    source_meta = soup.find("meta", property="marker:source")
    source = source_meta.get("content", "") if source_meta else ""
    if not source:
        # Запасной вариант: ищем в тексте
        source_span = soup.find(string=re.compile(r"Источник:"))
        if source_span:
            source = source_span.parent.get_text(strip=True).replace("Источник:", "").strip()

    # Section
    section_meta = soup.find("meta", property="article:section")
    section = section_meta.get("content", "") if section_meta else ""
    if not section:
        # Извлекаем из URL
        match = re.search(r'mail\.ru/([^/]+)/\d+/', url)
        if match:
            section = match.group(1)

    # Body
    body_tag = soup.find(attrs={"itemprop": "articleBody"})
    body = ""
    if body_tag:
        paragraphs = body_tag.find_all("p")
        body = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

    if not title and not body:
        return None

    return {
        "url": url,
        "title": title,
        "author": author,
        "date_published": date_published,
        "section": section,
        "source": source,
        "body": body,
        "body_length": len(body),
    }


def _get_month_links() -> list[str]:
    """Получает список всех месяцев из sitemap."""
    resp = _get(BASE_URL + "/sitemap/")
    if resp is None:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    links = set()

    # Строгий паттерн для месяца: /sitemap/YYYY-month/
    # Например: /sitemap/2024-august/ или /sitemap/2026-july/
    month_pattern = re.compile(r'^/sitemap/\d{4}-[a-z]+/$')

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if month_pattern.match(href):
            if not href.startswith("http"):
                href = BASE_URL + href
            links.add(href)

    return sorted(list(links))


def _get_day_links(month_url: str) -> list[str]:
    """Получает список всех дней из страницы месяца."""
    resp = _get(month_url)
    if resp is None:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    links = set()

    # Строгий паттерн для дня: /sitemap/YYYY-month/D/
    # Например: /sitemap/2024-august/1/ или /sitemap/2026-july/31/
    day_pattern = re.compile(r'/sitemap/\d{4}-[a-z]+/\d+/$')

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            href = BASE_URL + href

        # Проверяем, что это именно ссылка на день
        if day_pattern.search(href):
            links.add(href)

    return sorted(list(links))


def _get_article_links(day_url: str) -> list[str]:
    """Получает список всех статей из страницы дня."""
    resp = _get(day_url)
    if resp is None:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    links = set()

    # Паттерн для относительного пути статьи: /rubric/ID/
    # Например: /society/62174598/ или /politics/71534184/
    rel_pattern = re.compile(r'^/[a-z]+/\d+/$')

    # Ищем ссылки внутри span.link__text
    for span in soup.find_all("span", class_="link__text"):
        a_tag = span.find_parent("a")
        if a_tag and a_tag.get("href"):
            href = a_tag.get("href")

            # Если это относительный путь (начинается с /)
            if href.startswith("/"):
                # Проверяем, что это статья (не sitemap, не рубрика)
                if rel_pattern.match(href):
                    # Добавляем BASE_URL
                    full_url = BASE_URL + href
                    links.add(full_url)
            # Если это абсолютный URL
            elif href.startswith("http"):
                # Проверяем, что это news.mail.ru (не sport, не pogoda)
                if href.startswith(BASE_URL):
                    # Извлекаем относительный путь
                    path = href.replace(BASE_URL, "")
                    if rel_pattern.match(path):
                        links.add(href)

    return sorted(list(links))

def collect_mail_links(cfg: dict, data_dir: str, limit: int = 0, fresh: bool = False, suffix: str = "") -> list[str]:
    links_file = os.path.join(data_dir, f"all_article_links{suffix}.txt")
    results_path = os.path.join(data_dir, f"parsed_articles{suffix}.json")
    progress_path = os.path.join(data_dir, f"parsing_progress{suffix}.json")
    sitemap_prog = os.path.join(data_dir, f"sitemap_progress{suffix}.json")
    stats_path = os.path.join(data_dir, f"stats{suffix}.json")

    print(f"sitemap: {cfg['name']}")

    print("Загружаю список месяцев...")
    month_links = _get_month_links()
    if not month_links:
        print("error: не удалось загрузить список месяцев")
        return []
    print(f"Найдено месяцев: {len(month_links)}")

    print("Загружаю список дней...")
    day_links = []
    for month_url in month_links:
        days = _get_day_links(month_url)
        day_links.extend(days)
    day_links = sorted(list(set(day_links)))
    print(f"Найдено дней: {len(day_links)}")

    if limit:
        day_links = day_links[:limit]
        print(f"limit: {limit} дней")

    if not fresh and os.path.exists(sitemap_prog):
        with open(sitemap_prog, encoding="utf-8") as f:
            sp = json.load(f)
        done_days = set(sp.get("processed_days", []))
        all_articles = sp.get("articles", [])
        all_urls = [a["url"] for a in all_articles]
        days_to_process = [d for d in day_links if d not in done_days]
        print(f"Уже обработано дней: {len(done_days)}, осталось: {len(days_to_process)}")
        if not days_to_process:
            print("Все дни уже обработаны — используй --fresh чтобы начать заново")
            return all_urls
    else:
        done_days = set()
        all_articles = []
        all_urls = []
        days_to_process = day_links

    append_lock = threading.Lock()
    total_days = len(days_to_process)
    done_count = [0]
    day_stats = {}

    def _process_day(day_url: str) -> None:
        try:
            article_urls = _get_article_links(day_url)
        except Exception as e:
            print(f"[{day_url}] ошибка получения списка статей: {e}")
            return

        now = datetime.now().isoformat()
        day_articles = []
        for url in article_urls:
            if url in all_urls:
                continue
            article = _parse_article(url)
            if article:
                article["parsed_at"] = now
                day_articles.append(article)

        with append_lock:
            done_count[0] += 1
            done_days.add(day_url)
            day_stats[day_url] = {"count": len(day_articles)}
            all_articles.extend(day_articles)
            all_urls.extend([a["url"] for a in day_articles])
            print(f"[{done_count[0]}/{total_days}] {day_url}: +{len(day_articles)} (итого {len(all_articles)})")
            _save_sitemap_progress(sitemap_prog, done_days, all_articles, all_urls,
                                   results_path, progress_path, links_file)

    if total_days:
        print(f"\nОбходим {total_days} дней (workers={SITEMAP_WORKERS})...")
        run_started = datetime.now().isoformat()
        with ThreadPoolExecutor(max_workers=SITEMAP_WORKERS) as executor:
            list(executor.map(_process_day, days_to_process))

        _save_sitemap_progress(sitemap_prog, done_days, all_articles, all_urls,
                               results_path, progress_path, links_file)

        new_total = sum(v["count"] for v in day_stats.values())
        print(f"\n{'─' * 50}")
        print(f"Прогон завершён: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Обработано дней:   {len(day_stats)}")
        print(f"Новых статей:      {new_total}")
        print(f"Всего в базе:      {len(all_articles)}")
        print(f"{'─' * 50}")

        stats_data = {}
        if os.path.exists(stats_path):
            try:
                with open(stats_path, encoding="utf-8") as f:
                    stats_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                stats_data = {}

        runs = stats_data.get("runs", [])
        runs.append({
            "started_at": run_started,
            "finished_at": datetime.now().isoformat(),
            "fresh": fresh,
            "days_in_run": len(day_stats),
            "articles_in_run": new_total,
            "total_in_db": len(all_articles),
            "per_day": day_stats,
        })

        stats_data["runs"] = runs
        stats_data["total_days_done"] = len(done_days)
        stats_data["total_articles"] = len(all_articles)
        stats_data["last_updated"] = datetime.now().isoformat()

        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats_data, f, ensure_ascii=False, indent=2)
        print(f"Статистика сохранена: {stats_path}")

    return all_urls


def _save_sitemap_progress(sitemap_prog, done_days, all_articles, all_urls,
                           results_path, progress_path, links_file):
    os.makedirs(os.path.dirname(sitemap_prog), exist_ok=True)
    with open(sitemap_prog, "w", encoding="utf-8") as f:
        json.dump(
            {"processed_days": list(done_days), "articles": all_articles,
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

def fetch_mail_article(url: str) -> dict | None:
    """Запасной метод: загружает одну статью по URL (для шага parse)."""
    return _parse_article(url)