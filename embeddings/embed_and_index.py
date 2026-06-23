from dataclasses import dataclass
# from dataclasses import dataclass, field    # Для GliNER
from typing import Optional

from sentence_transformers import SentenceTransformer, CrossEncoder
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

import os
MODEL_NAME = os.getenv("BGE_MODEL_PATH", "BAAI/bge-m3")
RERANKER_MODEL = os.getenv("RERANKER_MODEL_PATH", "BAAI/bge-reranker-v2-m3")
# MODEL_NAME = "BAAI/bge-m3"
# RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
COLLECTION = "news_chunks"
VECTOR_SIZE = 1024  # размерность dense-вектора BGE-M3
BATCH_SIZE = 64


@dataclass
class IndexableChunk:
    chunk_id: int
    chunk_text: str
    payload: dict
    article_id: int


class NewsIndexer:
    def __init__(self, qdrant_url: Optional[str] = None, api_key: Optional[str] = None):
        # None → in-memory Qdrant для тестов без Docker
        self.model = SentenceTransformer(MODEL_NAME)
        if qdrant_url:
            self.client = QdrantClient(url=qdrant_url, api_key=api_key)
        else:
            self.client = QdrantClient(":memory:")
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        names = {c.name for c in self.client.get_collections().collections}
        if COLLECTION not in names:
            self.client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.DOT), # DOT используем так как вектора
                # уже нормированы (BGE-M3) и dot(a, b) = cos(a, b), однако DOT в Qdrant быстрее.
            )

    def index(self, chunks: list[IndexableChunk]) -> None:
        # upsert идемпотентен — повторный вызов с теми же chunk_id безопасен
        # обсуждали это с Сергеем на случай редактируемой статьи и способ перезаписи чанка
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            vectors = self._embed_passages([c.chunk_text for c in batch])
            points = [
                PointStruct(
                    id=c.chunk_id,
                    vector=v,
                    payload=c.payload
                )
                for c, v in zip(batch, vectors)
            ]
            self.client.upsert(collection_name=COLLECTION, points=points)

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        # возвращает (chunk_id, score) в порядке убывания релевантности
        # не тянем текст чанков, тексты отдельно в Postgres
        vector = self._embed_query(query)
        results = self.client.search(
            collection_name=COLLECTION,
            query_vector=vector,
            limit=top_k,
        )
        return [(r.id, r.score) for r in results]

    def _embed_passages(self, texts: list[str]) -> list[list[float]]:
        prefixed = [f"passage: {t}" for t in texts]
        return self.model.encode(
            prefixed, normalize_embeddings=True, batch_size=BATCH_SIZE # normalize_embeddings=True — для DOT product
        ).tolist()

    def _embed_query(self, query: str) -> list[float]:
        return self.model.encode(
            f"query: {query}", normalize_embeddings=True
        ).tolist()


class Reranker:
    def __init__(self, model_name: str = RERANKER_MODEL):
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, chunks: list[dict], top_n: int) -> list[dict]:
        if not chunks:
            return chunks
        pairs = [(query, c["text"]) for c in chunks]
        scores = self.model.predict(pairs).tolist()
        ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
        return [c for _, c in ranked[:top_n]]