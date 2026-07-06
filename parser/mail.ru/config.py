"""
Настройки парсера для news.mail.ru — новости.
Запуск (из корня репозитория):
python3 parser/parser/main.py parser/mail.ru sitemap [--limit N] [--fresh]
sitemap делает всё: обходит sitemap/ -> месяцы -> дни -> статьи,
сохраняет в parsed_articles.json и помечает все URL как обработанные.
Шаг parse завершается мгновенно ("nothing to parse").
--limit N: обработать только первые N дней
--fresh:   сбросить прогресс и начать заново
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from parsers import collect_mail_links

SITE_CONFIG = {
    "name": "Mail.ru News",
    "url_prefix": "https://news.mail.ru/",
    # Переопределяем сбор: вместо XML sitemap — обход HTML-карты сайта
    "collect_links": collect_mail_links,
    # fetch_article не нужен — sitemap собирает полные статьи сразу
    # Заглушки — не используются при наличии collect_links
    "sitemap_index":  "",
    "sitemap_filter": lambda u: False,
    "article_filter": lambda u: True,
}