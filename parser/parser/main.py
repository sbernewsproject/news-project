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

import importlib.util
import json
import os
import sys
import time
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from sitemap import collect_links
from article import fetch_article as _default_fetch_article

DELAY = 1.0


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


def load_progress(site_dir: str) -> dict:
    path = os.path.join(site_dir, "parsing_progress.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed_urls": [], "parsed_articles": []}


def save_progress(site_dir: str, processed: list, articles: list) -> None:
    path = os.path.join(site_dir, "parsing_progress.json")
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


def save_results(site_dir: str, articles: list) -> None:
    path = os.path.join(site_dir, "parsed_articles.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)


def cmd_sitemap(cfg: dict, site_dir: str, limit: int = 0, fresh: bool = False) -> None:
    links = collect_links(cfg, site_dir, limit=limit, fresh=fresh)
    if links:
        print("sample urls:")
        for l in links[:3]:
            print(f"  {l}")


def cmd_parse(cfg: dict, site_dir: str, limit: int = 0, fresh: bool = False) -> None:
    links_path = os.path.join(site_dir, "all_article_links.txt")
    if not os.path.exists(links_path):
        print(f"error: {links_path} not found")
        print("run sitemap step first")
        return

    with open(links_path, "r", encoding="utf-8") as f:
        all_links = [l.strip() for l in f if l.strip()]

    # Сайт может определить свой fetch_article в config.py
    fetch_fn = cfg.get("fetch_article", _default_fetch_article)

    print(f"parse: {cfg['name']}")
    print(f"links loaded: {len(all_links)}")

    if fresh:
        processed = set()
        articles  = []
        print("fresh: ignoring saved progress")
    else:
        progress  = load_progress(site_dir)
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

    print(f"starting: {len(todo)} articles")

    start      = datetime.now()
    ok, fail   = 0, 0
    failed_log = os.path.join(site_dir, "failed_urls.txt")

    for i, url in enumerate(todo, 1):
        slug = url.replace(cfg["url_prefix"], "")
        print(f"[{i}/{len(todo)}] {slug[:80]}")

        article = fetch_fn(url)

        if article and "error" not in article:
            articles.append({**article, "parsed_at": datetime.now().isoformat()})
            ok += 1
            body_len = article.get("body_length", len(article.get("body", "") or ""))
            print(f"  ok: {article.get('title', '')[:55]} ({body_len} chars)")
        else:
            fail += 1
            err = article.get("error", "") if article else ""
            print(f"  failed{': ' + err if err else ''}")
            with open(failed_log, "a", encoding="utf-8") as f:
                f.write(url + "\n")

        processed.add(url)
        if not fresh:
            save_progress(site_dir, list(processed), articles)
            save_results(site_dir, articles)

        if i % 10 == 0:
            elapsed = (datetime.now() - start).total_seconds()
            rate    = i / elapsed if elapsed > 0 else 0
            print(f"  progress: {i}/{len(todo)}, ok={ok}, fail={fail}, {rate:.1f}/sec")

        time.sleep(DELAY)

    if fresh:
        save_progress(site_dir, list(processed), articles)
        save_results(site_dir, articles)

    elapsed = (datetime.now() - start).total_seconds()
    print(f"done: ok={ok}, fail={fail}, total={len(articles)}, time={elapsed:.0f}s")
    print(f"results: {os.path.join(site_dir, 'parsed_articles.json')}")


def parse_args(argv: list) -> tuple:
    if len(argv) < 3:
        print(__doc__)
        sys.exit(1)

    site_arg = argv[1]
    command  = argv[2]
    limit    = 0
    fresh    = False

    i = 3
    while i < len(argv):
        if argv[i] == "--limit" and i + 1 < len(argv):
            limit = int(argv[i + 1])
            i += 2
        elif argv[i] == "--fresh":
            fresh = True
            i += 1
        else:
            i += 1

    return site_arg, command, limit, fresh


if __name__ == "__main__":
    site_arg, command, limit, fresh = parse_args(sys.argv)

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
        cmd_sitemap(cfg, site_dir, limit, fresh)
    elif command == "parse":
        cmd_parse(cfg, site_dir, limit, fresh)
    elif command == "all":
        cmd_sitemap(cfg, site_dir, limit, fresh)
        cmd_parse(cfg, site_dir, limit, fresh)
    else:
        print(f"error: unknown command '{command}'")
        print("available: sitemap, parse, all")
        sys.exit(1)
