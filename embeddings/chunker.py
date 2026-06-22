import hashlib
from dataclasses import dataclass
from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

@dataclass
class Article:
    article_id: int
    author: str
    title: str
    arttext: str
    arturl: str
    mark: int
    parsedate: str
    createdate: str
    types_id: int

@dataclass
class Chunk:
    article_id: int
    chunk_index: int  # порядковый номер внутри статьи
    text: str
    payload: dict     # метаданные для Qdrant

def chunk_article(article: Article) -> list[Chunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
    )
    prefix = (
        f"{article.title}\n"
        f"Источник: {article.arturl}\n"
        f"Дата: {article.createdate}\n\n"
    )
    pieces = splitter.split_text(article.arttext)
    return [
        Chunk(
            article_id=article.article_id,
            chunk_index=i,
            text=prefix + piece,
            payload={
                "article_id": article.article_id,
                "source": article.arturl,
                "published_at": article.createdate,
                "chunk_index": i,
                "content_hash": hashlib.sha256(
                    (prefix + piece).encode()
                ).hexdigest()[:16],
            }
        )
        for i, piece in enumerate(pieces)
    ]