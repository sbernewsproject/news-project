"""
Универсальный парсер новостных сайтов.

Использование:
  python3 parser/main.py <папка> sitemap [--limit N] [--fresh]
  python3 parser/main.py <папка> parse   [--limit N] [--fresh]
  python3 parser/main.py <папка> all     [--limit N] [--fresh]

--limit N   обработать только первые N единиц:
              sitemap — N sub-sitemap'ов,
              parse   — N статей.

--fresh     игнорировать сохранённый прогресс и начать с начала.
            Данные не удаляются, прогресс просто не читается в этом запуске.

Примеры:
  python3 parser/main.py komsomolskaya_pravda sitemap
  python3 parser/main.py komsomolskaya_pravda sitemap --limit 2
  python3 parser/main.py lenta.ru parse --limit 5
  python3 parser/main.py lenta.ru parse --limit 5 --fresh
  python3 parser/main.py komsomolskaya_pravda all
"""

import asyncio
import importlib.util
import json
import os
import random
import ssl
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import aiohttp
import certifi

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from sitemap import collect_links
from article import fetch_article as _default_fetch_article
from article import parse_html as _default_parse_html

DELAY         = 0.5   # пауза для старого sync-пути
WORKERS       = 10    # воркеров для sync-пути
ASYNC_WORKERS = 100   # concurrent соединений для async-пути

_ASYNC_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept-Encoding": "gzip, deflate",  # без br — aiohttp не умеет brotli без доп. пакета
    "Connection":      "keep-alive",
}


def load_site_config(site_dir: str) -> dict:
    config_path = os.path.join(site_dir, "config.py")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config.py not found in {site_dir}")

    spec = importlib.util.spec_from_file_location("site_config", config_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "SITE_CONFIG"):
        raise AttributeError(f"SITE_CONFIG not defined in {config_path}")

    return mod.SITE_CONFIG


def load_progress(site_dir: str, suffix: str = "") -> dict:
    path = os.path.join(site_dir, f"parsing_progress{suffix}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed_urls": [], "parsed_articles": []}


def save_progress(site_dir: str, processed: list, articles: list, suffix: str = "") -> None:
    path = os.path.join(site_dir, f"parsing_progress{suffix}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "processed_urls": processed,
                "parsed_articles": articles,
                "total": len(articles),
                "updated_at": datetime.now().isoformat(),
            },
            f, ensure_ascii=False, indent=2,
        )


def save_results(site_dir: str, articles: list, suffix: str = "") -> None:
    path = os.path.join(site_dir, f"parsed_articles{suffix}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)


def cmd_sitemap(cfg: dict, site_dir: str, limit: int = 0, fresh: bool = False, suffix: str = "") -> None:
    collect_fn = cfg.get("collect_links", collect_links)
    links = collect_fn(cfg, site_dir, limit=limit, fresh=fresh, suffix=suffix)
    if links:
        print("sample urls:")
        for l in links[:3]:
            print(f"  {l}")


async def _async_fetch_loop(
    parse_html_fn, cfg, site_dir, todo, workers_n,
    articles, processed, suffix, start,
):
    """Async core: download all pages concurrently, parse each synchronously."""
    lock       = asyncio.Lock()
    ok         = [0]
    fail       = [0]
    done       = [0]
    total      = len(todo)
    failed_log = os.path.join(site_dir, "failed_urls.txt")
    prefix     = cfg.get("url_prefix", "")

    # Bounded queue prevents creating millions of tasks upfront
    queue = asyncio.Queue(maxsize=workers_n * 4)

    async def _producer():
        for url in todo:
            await queue.put(url)
        for _ in range(workers_n):
            await queue.put(None)  # shutdown signals

    async def _worker(session):
        while True:
            url = await queue.get()
            if url is None:
                return

            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status == 200:
                        html    = await r.text()
                        article = parse_html_fn(url, html)
                    elif r.status == 404:
                        article = None
                    else:
                        article = {"error": f"HTTP {r.status}"}
            except asyncio.TimeoutError:
                article = {"error": "timeout"}
            except Exception as e:
                article = {"error": type(e).__name__}

            async with lock:
                done[0] += 1
                n = done[0]

                if article and "error" not in article:
                    articles.append({**article, "parsed_at": datetime.now().isoformat()})
                    ok[0] += 1
                    body_len = article.get("body_length", len(article.get("body", "") or ""))
                    print(f"[{n}/{total}] ok: {article.get('title', '')[:55]} ({body_len} chars)")
                else:
                    fail[0] += 1
                    err  = (article or {}).get("error", "")
                    slug = url.replace(prefix, "")
                    print(f"[{n}/{total}] fail {slug[:60]}{': ' + err if err else ''}")
                    with open(failed_log, "a", encoding="utf-8") as f:
                        f.write(url + "\n")

                processed.add(url)

                if n % 200 == 0 or n == total:
                    save_progress(site_dir, list(processed), articles, suffix)
                    save_results(site_dir, articles, suffix)
                    elapsed = (datetime.now() - start).total_seconds()
                    rate    = n / elapsed if elapsed > 0 else 0
                    print(f"  progress: {n}/{total}, ok={ok[0]}, fail={fail[0]}, {rate:.1f}/sec")

    ssl_ctx   = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(limit=workers_n, ttl_dns_cache=300, ssl=ssl_ctx)
    async with aiohttp.ClientSession(headers=_ASYNC_HEADERS, connector=connector) as session:
        prod    = asyncio.create_task(_producer())
        workers = [asyncio.create_task(_worker(session)) for _ in range(workers_n)]
        await asyncio.gather(prod, *workers)

    return ok[0], fail[0]


def cmd_parse(cfg: dict, site_dir: str, limit: int = 0, fresh: bool = False, suffix: str = "") -> None:
    links_path = os.path.join(site_dir, f"all_article_links{suffix}.txt")
    if not os.path.exists(links_path):
        print(f"error: {links_path} not found")
        print("run sitemap step first")
        return

    with open(links_path, "r", encoding="utf-8") as f:
        all_links = [l.strip() for l in f if l.strip()]

    print(f"parse: {cfg['name']}")
    print(f"links loaded: {len(all_links)}")

    if fresh:
        processed = set()
        articles  = []
        print("fresh: ignoring saved progress")
    else:
        progress  = load_progress(site_dir, suffix)
        processed = set(progress.get("processed_urls", []))
        articles  = progress.get("parsed_articles", [])

    todo = [u for u in all_links if u not in processed]
    print(f"already parsed: {len(articles)}, remaining: {len(todo)}")

    if not todo:
        print("nothing to parse")
        return

    if limit:
        todo = todo[:limit]
        print(f"limit: {limit} articles")

    # Dispatch: async если есть parse_html или нет кастомного fetch_article
    parse_html_fn = cfg.get("parse_html")
    fetch_fn      = cfg.get("fetch_article")
    use_async     = parse_html_fn is not None or fetch_fn is None

    start = datetime.now()

    if use_async:
        if parse_html_fn is None:
            parse_html_fn = _default_parse_html
        workers = cfg.get("parse_workers", ASYNC_WORKERS)
        print(f"starting: {len(todo)} articles async (workers={workers})")
        ok, fail = asyncio.run(
            _async_fetch_loop(parse_html_fn, cfg, site_dir, todo, workers,
                              articles, processed, suffix, start)
        )
    else:
        # Старый sync-путь (для сайтов с кастомным fetch_article без parse_html)
        workers = cfg.get("parse_workers", WORKERS)
        delay   = cfg.get("parse_delay",   DELAY)
        print(f"starting: {len(todo)} articles sync (workers={workers}, delay={delay}s)")
        ok, fail = _sync_fetch_loop(fetch_fn, cfg, site_dir, todo, workers, delay,
                                    articles, processed, suffix, start, fresh)

    elapsed  = (datetime.now() - start).total_seconds()
    out_file = os.path.join(site_dir, f"parsed_articles{suffix}.json")
    print(f"done: ok={ok}, fail={fail}, total={len(articles)}, time={elapsed:.0f}s")
    print(f"results: {out_file}")


def _sync_fetch_loop(fetch_fn, cfg, site_dir, todo, workers, delay,
                     articles, processed, suffix, start, fresh):
    ok, fail = 0, 0
    done     = 0
    lock     = threading.Lock()
    failed_log = os.path.join(site_dir, "failed_urls.txt")

    def _fetch(url):
        time.sleep(delay + random.uniform(0, delay * 0.3))
        return url, fetch_fn(url)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_fetch, url): url for url in todo}
        for future in as_completed(futures):
            url  = futures[future]
            slug = url.replace(cfg.get("url_prefix", ""), "")
            try:
                _, article = future.result()
            except Exception as e:
                article = {"error": str(e)}

            with lock:
                done += 1
                if article and "error" not in article:
                    articles.append({**article, "parsed_at": datetime.now().isoformat()})
                    ok += 1
                    body_len = article.get("body_length", len(article.get("body", "") or ""))
                    print(f"[{done}/{len(todo)}] ok: {article.get('title', '')[:55]} ({body_len} chars)")
                else:
                    fail += 1
                    err = article.get("error", "") if article else ""
                    print(f"[{done}/{len(todo)}] fail {slug[:60]}{': ' + err if err else ''}")
                    with open(failed_log, "a", encoding="utf-8") as f:
                        f.write(url + "\n")

                processed.add(url)
                if not fresh:
                    save_progress(site_dir, list(processed), articles, suffix)
                    save_results(site_dir, articles, suffix)

                if done % 10 == 0:
                    elapsed = (datetime.now() - start).total_seconds()
                    rate    = done / elapsed if elapsed > 0 else 0
                    print(f"  progress: {done}/{len(todo)}, ok={ok}, fail={fail}, {rate:.1f}/sec")

    if fresh:
        save_progress(site_dir, list(processed), articles, suffix)
        save_results(site_dir, articles, suffix)

    return ok, fail


def parse_args(argv: list) -> tuple:
    if len(argv) < 3:
        print(__doc__)
        sys.exit(1)

    site_arg = argv[1]
    command  = argv[2]
    limit    = 0
    fresh    = False
    suffix   = ""

    i = 3
    while i < len(argv):
        if argv[i] == "--limit" and i + 1 < len(argv):
            limit = int(argv[i + 1])
            i += 2
        elif argv[i] == "--fresh":
            fresh = True
            i += 1
        elif argv[i] == "--suffix" and i + 1 < len(argv):
            suffix = argv[i + 1]
            i += 2
        else:
            i += 1

    return site_arg, command, limit, fresh, suffix


if __name__ == "__main__":
    site_arg, command, limit, fresh, suffix = parse_args(sys.argv)

    site_dir = os.path.abspath(site_arg)
    if not os.path.isdir(site_dir):
        print(f"error: directory not found: {site_dir}")
        sys.exit(1)

    try:
        cfg = load_site_config(site_dir)
    except (FileNotFoundError, AttributeError) as e:
        print(f"error: {e}")
        sys.exit(1)

    if command == "sitemap":
        cmd_sitemap(cfg, site_dir, limit, fresh, suffix)
    elif command == "parse":
        cmd_parse(cfg, site_dir, limit, fresh, suffix)
    elif command == "all":
        cmd_sitemap(cfg, site_dir, limit, fresh, suffix)
        cmd_parse(cfg, site_dir, limit, fresh, suffix)
    else:
        print(f"error: unknown command '{command}'")
        print("available: sitemap, parse, all")
        sys.exit(1)
