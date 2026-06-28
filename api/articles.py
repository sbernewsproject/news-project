"""
REST-эндпоинты ленты новостей из Postgres.

  GET /api/articles        — лента (cursor-пагинация, фильтры, гибридный поиск при q)
  GET /api/articles/{id}   — полная статья
  GET /api/themes          — темы для сайдбара
  GET /api/types           — типы (Новость/Отзыв)
"""

from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query

from api.db import get_pool
from api.schemas import ArticleCard, ArticleDetail, ArticlesPage, Theme, Type
from api.search import hybrid_search

router = APIRouter(prefix="/api")


def _source_name(url: str) -> str:
    """Домен источника без www: https://www.banki.ru/... → banki.ru."""
    host = urlparse(url).netloc
    return host[4:] if host.startswith("www.") else host


def _card(row) -> ArticleCard:
    summary = (row["summary"] or "").strip()
    if row["truncated"]:
        summary = summary.rstrip() + "…"
    return ArticleCard(
        id=row["article_id"],
        title=row["title"],
        summary=summary,
        source=row["arturl"],
        sourceName=_source_name(row["arturl"]),
        date=row["createdate"],
        type=row["types_name"],
        topics=list(row["topics"] or []),
        mark=row["mark"],
    )


# Общий SELECT для карточек ленты; topics — массивом одним подзапросом.
_CARD_SELECT = """
    SELECT a.article_id, a.title,
           left(a.arttext, 200) AS summary,
           char_length(a.arttext) > 200 AS truncated,
           a.arturl, a.createdate, a.mark, t.types_name,
           (SELECT array_agg(th.theme_name)
              FROM article_theme at_ JOIN theme th ON th.theme_id = at_.theme_id
             WHERE at_.article_id = a.article_id) AS topics
    FROM article a
    LEFT JOIN types t ON t.types_id = a.types_id
"""


@router.get("/articles", response_model=ArticlesPage)
async def list_articles(
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[int] = Query(None, description="article_id; вернёт записи строго меньше него"),
    theme: Optional[list[int]] = Query(None, description="theme_id, можно несколько"),
    type: Optional[int] = Query(None, description="types_id"),
    q: Optional[str] = Query(None, description="строка поиска (гибридный поиск)"),
) -> ArticlesPage:
    pool = get_pool()

    # Поиск: гибридный (FTS + семантика), возвращаем самые релевантные одной страницей.
    if q and q.strip():
        ids = await hybrid_search(q.strip(), limit)
        if not ids:
            return ArticlesPage(items=[], next_cursor=None)
        rows = await pool.fetch(
            _CARD_SELECT
            + " WHERE a.article_id = ANY($1::int[]) ORDER BY array_position($1::int[], a.article_id)",
            ids,
        )
        return ArticlesPage(items=[_card(r) for r in rows], next_cursor=None)

    # Обычная лента: keyset-пагинация по article_id DESC.
    conds: list[str] = []
    params: list = []
    if cursor is not None:
        params.append(cursor)
        conds.append(f"a.article_id < ${len(params)}")
    if type is not None:
        params.append(type)
        conds.append(f"a.types_id = ${len(params)}")
    if theme:
        params.append(theme)
        conds.append(
            f"EXISTS (SELECT 1 FROM article_theme at2 "
            f"WHERE at2.article_id = a.article_id AND at2.theme_id = ANY(${len(params)}::int[]))"
        )

    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    params.append(limit + 1)  # +1 чтобы понять, есть ли следующая страница
    sql = _CARD_SELECT + where + f" ORDER BY a.article_id DESC LIMIT ${len(params)}"

    rows = await pool.fetch(sql, *params)
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = rows[-1]["article_id"]
    return ArticlesPage(items=[_card(r) for r in rows], next_cursor=next_cursor)


@router.get("/articles/{article_id}", response_model=ArticleDetail)
async def get_article(article_id: int) -> ArticleDetail:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT a.article_id, a.title, a.arttext, a.author, a.arturl,
               a.createdate, a.parsedate, a.mark, t.types_name,
               (SELECT array_agg(th.theme_name)
                  FROM article_theme at_ JOIN theme th ON th.theme_id = at_.theme_id
                 WHERE at_.article_id = a.article_id) AS topics
        FROM article a
        LEFT JOIN types t ON t.types_id = a.types_id
        WHERE a.article_id = $1
        """,
        article_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return ArticleDetail(
        id=row["article_id"],
        title=row["title"],
        body=row["arttext"],
        author=row["author"],
        source=row["arturl"],
        sourceName=_source_name(row["arturl"]),
        date=row["createdate"],
        parsedate=row["parsedate"],
        type=row["types_name"],
        topics=list(row["topics"] or []),
        mark=row["mark"],
    )


@router.get("/themes", response_model=list[Theme])
async def list_themes() -> list[Theme]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT th.theme_id, th.theme_name, count(at_.article_id) AS cnt
        FROM theme th
        LEFT JOIN article_theme at_ ON at_.theme_id = th.theme_id
        GROUP BY th.theme_id, th.theme_name
        ORDER BY cnt DESC
        """
    )
    return [Theme(id=r["theme_id"], name=r["theme_name"], count=r["cnt"]) for r in rows]


@router.get("/types", response_model=list[Type])
async def list_types() -> list[Type]:
    pool = get_pool()
    rows = await pool.fetch("SELECT types_id, types_name FROM types ORDER BY types_id")
    return [Type(id=r["types_id"], name=r["types_name"]) for r in rows]
