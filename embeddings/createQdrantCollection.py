from qdrant_client import QdrantClient, models
from qdrant_client.http.models import PointStruct
from qdrant_client.models import Distance, VectorParams
from sentence_transformers import SentenceTransformer

client = QdrantClient(url="http://127.0.0.1:6333")
client.create_collection(
    collection_name="newsChunks",
    vectors_config=VectorParams(
        size=1024,
        distance=models.Distance.COSINE
    )
)

