import gzip
import json
import os
import time
import xml.etree.ElementTree as ET

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
}
DELAY = 0.5


def _load_progress(data_dir: str) -> dict:
    path = os.path.join(data_dir, "sitemap_progress.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed_sitemaps": [], "all_links": []}


def _save_progress(data_dir: str, processed: list, links: list) -> None:
    path = os.path.join(data_dir, "sitemap_progress.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"processed_sitemaps": processed, "all_links": links},
                  f, ensure_ascii=False, indent=2)


def _save_links(data_dir: str, links: list) -> None:
    path = os.path.join(data_dir, "all_article_links.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(links))


def _fetch_xml(url: str) -> ET.Element | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        content = r.content
        try:
            content = gzip.decompress(content)
        except Exception:
            pass
        return ET.fromstring(content)
    except Exception as e:
        print(f"  error: {url}: {e}")
        return None


def _extract_locs(root: ET.Element) -> list[str]:
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [el.text for el in root.findall(".//sm:loc", ns) if el.text]


def collect_links(site_cfg: dict, data_dir: str, limit: int = 0, fresh: bool = False) -> list[str]:
    """
    Собирает ссылки на статьи через sitemap.

    limit — максимум новых sub-sitemap'ов для обработки (0 = все).
    fresh — игнорировать сохранённый прогресс и начать с начала.
    """
    os.makedirs(data_dir, exist_ok=True)

    if fresh:
        processed = []
        all_links = []
        print(f"sitemap: {site_cfg['name']}")
        print("fresh: ignoring saved progress")
    else:
        progress  = _load_progress(data_dir)
        processed = progress.get("processed_sitemaps", progress.get("processed_urls", []))
        all_links = progress.get("all_links", [])
        print(f"sitemap: {site_cfg['name']}")
        print(f"progress: {len(all_links)} links, {len(processed)} sitemaps done")

    seen_set  = set(all_links)

    index_root = _fetch_xml(site_cfg["sitemap_index"])
    if index_root is None:
        print("error: failed to load sitemap index")
        return all_links

    all_subs = _extract_locs(index_root)
    subs     = [u for u in all_subs if site_cfg["sitemap_filter"](u)]
    print(f"sitemaps: {len(subs)} to process")

    if limit:
        pending = [u for u in subs if u not in processed]
        subs = [u for u in subs if u in processed] + pending[:limit]
        print(f"limit: processing {limit} new sitemaps")

    for i, sitemap_url in enumerate(subs, 1):
        short = sitemap_url.replace(site_cfg["url_prefix"], "")

        if sitemap_url in processed:
            print(f"[{i}/{len(subs)}] skip {short}")
            continue

        print(f"[{i}/{len(subs)}] {short}")
        root = _fetch_xml(sitemap_url)

        if root is None:
            processed.append(sitemap_url)
            _save_progress(data_dir, processed, all_links)
            continue

        locs     = _extract_locs(root)
        new_urls = [u for u in locs if site_cfg["article_filter"](u) and u not in seen_set]

        for u in new_urls:
            all_links.append(u)
            seen_set.add(u)

        processed.append(sitemap_url)
        _save_progress(data_dir, processed, all_links)
        _save_links(data_dir, all_links)

        print(f"  +{len(new_urls)} new, total: {len(all_links)}")

        time.sleep(DELAY)

    print(f"done: {len(all_links)} links -> {os.path.join(data_dir, 'all_article_links.txt')}")
    return all_links
