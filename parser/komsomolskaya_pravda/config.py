"""
Настройки парсера для Комсомольской Правды.
"""

SITE_CONFIG = {
    "name": "Комсомольская Правда",
    "sitemap_index": "https://www.kp.ru/sitemap.xml",
    "sitemap_gzip": False,
    "sitemap_filter": lambda url: not url.endswith(".gz"),
    "article_filter": lambda url: "/daily/" in url and "www.kp.ru/daily/" in url,
    "url_prefix": "https://www.kp.ru/",
    "parse_workers": 100,
}
