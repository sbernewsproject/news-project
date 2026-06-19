import hashlib
from dataclasses import dataclass
from datetime import date

from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


@dataclass
class Article:
    article_id: int
    title: str
    source: str
    published_at: date
    language: str
    content: str


@dataclass
class Chunk:
    article_id: int
    position: int
    text: str
    content_hash: str

# здесь определяются метаданные в векторной БД, то что мы подаем в payload
# используем recursive character split тут можно поиграться с тем какой способ делать
def chunk_article(article: Article) -> list[Chunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
    )
    prefix = (
        f"{article.title}\n"
        f"Источник: {article.source}\n"
        f"Дата: {article.published_at}\n\n"
    )
    pieces = splitter.split_text(article.content)
    return [
        Chunk(
            article_id=article.article_id,
            position=i,
            text=prefix + piece,
            content_hash=hashlib.sha256((prefix + piece).encode()).hexdigest()[:16],
        )
        for i, piece in enumerate(pieces)
    ]