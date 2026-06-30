"""Pydantic-модели ответов API ленты новостей."""

from typing import Optional

from pydantic import BaseModel


class ArticleCard(BaseModel):
    id: int
    title: str
    summary: str
    source: str
    sourceName: str
    date: str
    type: Optional[str] = None
    topics: list[str] = []
    mark: Optional[int] = None


class ArticleDetail(BaseModel):
    id: int
    title: str
    body: str
    author: str
    source: str
    sourceName: str
    date: str
    parsedate: str
    type: Optional[str] = None
    topics: list[str] = []
    mark: Optional[int] = None


class ArticlesPage(BaseModel):
    items: list[ArticleCard]
    next_cursor: Optional[int] = None


class Theme(BaseModel):
    id: int
    name: str
    count: Optional[int] = None


class Type(BaseModel):
    id: int
    name: str
