from createQdrantCollection import client
from qdrant_client import QdrantClient, models
from qdrant_client.http.models import PointStruct
from qdrant_client.models import Distance, VectorParams
from sentence_transformers import SentenceTransformer
from sympy.codegen.ast import String

model = SentenceTransformer("BAAI/bge-m3")

def add_chunks(chunks:list[dict]):
    texts=["passage" + c["text"] for c in chenks]
    vectors=model.encode(texts)
    points=[
        PointStruct(
            id=chunk["chunk_id"],
            vector=vectors[i],
            payload=chunk["payload"]
        )
        for i, chunk in enumerate(chunks)
    ]
    client.upsert(
        collection_name="newsChunks",
        points=points
    )

def search_chunks(query:String):
    query_question="query: "+ query
    query_vector=model.encode(query_question)

    closest_chunks=client.search(
        collection_name="news_chunks",
        query_vector=query_vector,
        limit=10,
        with_payload=True
    )
    chunks_ids=[chunk.id for chunk in closest_chunks]
    return chunks_ids




