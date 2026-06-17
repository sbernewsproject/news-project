from dataclasses import dataclass
from typing import Optional

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

MODEL_NAME = "BAAI/bge-m3"
COLLECTION = "news_chunks"
VECTOR_SIZE = 1024  # размерность dense-вектора BGE-M3
BATCH_SIZE = 64


@dataclass
class IndexableChunk:
    chunk_id: int       # BIGSERIAL из Postgres
    article_id: int
    text: str           # обогащённый текст: префикс (заголовок/источник/дата) + кусок
    source: str
    published_at: str   # дата в формате ISO-8601
    language: str


class NewsIndexer:
    def __init__(self, qdrant_url: Optional[str] = None):
        # None → in-memory Qdrant для тестов без Docker
        self.model = SentenceTransformer(MODEL_NAME)
        self.client = QdrantClient(url=qdrant_url) if qdrant_url else QdrantClient(":memory:")
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        names = {c.name for c in self.client.get_collections().collections}
        if COLLECTION not in names:
            self.client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.DOT),
            )

    def index(self, chunks: list[IndexableChunk]) -> None:
        # upsert идемпотентен — повторный вызов с теми же chunk_id безопасен
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            vectors = self._embed_passages([c.text for c in batch])
            points = [
                PointStruct(
                    id=c.chunk_id,
                    vector=v,
                    payload={
                        "chunk_id": c.chunk_id,
                        "article_id": c.article_id,
                        "source": c.source,
                        "published_at": c.published_at,
                        "language": c.language,
                    },
                )
                for c, v in zip(batch, vectors)
            ]
            self.client.upsert(collection_name=COLLECTION, points=points)

    def search(self, query: str, top_k: int = 10) -> list[int]:
        # возвращает chunk_id в порядке убывания релевантности
        vector = self._embed_query(query)
        results = self.client.search(
            collection_name=COLLECTION,
            query_vector=vector,
            limit=top_k,
        )
        return [int(r.payload["chunk_id"]) for r in results]

    def _embed_passages(self, texts: list[str]) -> list[list[float]]:
        prefixed = [f"passage: {t}" for t in texts]
        return self.model.encode(
            prefixed, normalize_embeddings=True, batch_size=BATCH_SIZE
        ).tolist()

    def _embed_query(self, query: str) -> list[float]:
        return self.model.encode(
            f"query: {query}", normalize_embeddings=True
        ).tolist()