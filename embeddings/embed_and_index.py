from dataclasses import dataclass
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

# Sparse BM25 через fastembed (опционально)
try:
    from fastembed import SparseTextEmbedding as _SparseModel
    from qdrant_client.models import (
        SparseVector as _QSparseVector,
        SparseVectorParams as _SparseVectorParams,
        SparseIndexParams as _SparseIndexParams,
        Prefetch as _Prefetch,
        FusionQuery as _FusionQuery,
        Fusion as _Fusion,
    )
    _sparse_encoder = _SparseModel(model_name="Qdrant/bm25")
    _HAS_SPARSE = True
except Exception:
    _HAS_SPARSE = False


@dataclass
class IndexableChunk:
    chunk_id: int
    chunk_text: str
    payload: dict
    article_id: int


class NewsIndexer:
    def __init__(self, qdrant_url: Optional[str] = None, api_key: Optional[str] = None):
        self.model = SentenceTransformer(MODEL_NAME)
        if qdrant_url:
            self.client = QdrantClient(url=qdrant_url, api_key=api_key, timeout=120)
        else:
            self.client = QdrantClient(":memory:")
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        names = {c.name for c in self.client.get_collections().collections}
        if COLLECTION not in names:
            self.client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.DOT),  # DOT используем так как вектора
                # уже нормированы (BGE-M3) и dot(a, b) = cos(a, b), однако DOT в Qdrant быстрее.
            )
        # Добавляем sparse BM25 конфиг если fastembed доступен
        if _HAS_SPARSE:
            try:
                self.client.update_collection(
                    collection_name=COLLECTION,
                    sparse_vectors_config={
                        "bm25": _SparseVectorParams(
                            index=_SparseIndexParams(on_disk=False)
                        )
                    },
                )
            except Exception:
                pass

    def index(self, chunks: list[IndexableChunk]) -> None:
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            texts = [c.chunk_text for c in batch]
            dense_vecs = self._embed_passages(texts)

            sparse_vecs = list(_sparse_encoder.embed(texts)) if _HAS_SPARSE else None

            points = []
            for i, (c, dv) in enumerate(zip(batch, dense_vecs)):
                if sparse_vecs:
                    sv = sparse_vecs[i]
                    vector = {
                        "": dv,
                        "bm25": _QSparseVector(
                            indices=sv.indices.tolist(),
                            values=sv.values.tolist(),
                        ),
                    }
                else:
                    vector = dv
                points.append(PointStruct(id=c.chunk_id, vector=vector, payload=c.payload))

            self.client.upsert(collection_name=COLLECTION, points=points)

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        dense_vec = self._embed_query(query)

        if _HAS_SPARSE:
            sq = list(_sparse_encoder.query_embed(query))[0]
            sparse_q = _QSparseVector(
                indices=sq.indices.tolist(),
                values=sq.values.tolist(),
            )
            results = self.client.query_points(
                collection_name=COLLECTION,
                prefetch=[
                    _Prefetch(query=dense_vec, limit=top_k),
                    _Prefetch(query=sparse_q, using="bm25", limit=top_k),
                ],
                query=_FusionQuery(fusion=_Fusion.RRF),
                limit=top_k,
            )
        else:
            results = self.client.query_points(
                collection_name=COLLECTION,
                query=dense_vec,
                limit=top_k,
            )

        return [(r.id, r.score) for r in results.points]

    def _embed_passages(self, texts: list[str]) -> list[list[float]]:
        prefixed = [f"passage: {t}" for t in texts]
        return self.model.encode(
            prefixed, normalize_embeddings=True, batch_size=BATCH_SIZE
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