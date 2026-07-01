"""
RAG-сервис для GPU-хоста.

Здесь живут модели (BGE-M3, реранкер) и оркестрация RAG-цепочки. Лёгкий API на
VPS (api/main.py) проксирует сюда POST /query. Postgres и Qdrant этот сервис
дёргает по сети (POSTGRES_DSN / QDRANT_URL указывают на VPS), генерацию — через
локальный Ollama (OLLAMA_URL).

Запуск: uvicorn rag.server:app --host 0.0.0.0 --port 8001
"""


import json as _json
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

_chain = None  # RAGChain, поднимается один раз на старте (загрузка моделей)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _chain
    from rag.chain import RAGChain
    _chain = RAGChain(
        qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        api_key=os.getenv("QDRANT_API_KEY"),
    )
    yield


app = FastAPI(title="news-rag", version="0.1.0", lifespan=lifespan)


class QueryRequest(BaseModel):
    query: str
    top_k: int = 10


class QueryResponse(BaseModel):
    answer: str
    route: Optional[str] = None


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    from rag.chain import _route
    try:
        result = await _chain.answer(req.query, top_k=req.top_k)
        return QueryResponse(answer=result, route=_route(req.query))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query/stream")
async def query_stream(req: QueryRequest):
    async def gen():
        try:
            async for token in _chain.stream_answer(req.query, top_k=req.top_k):
                yield f"data: {_json.dumps({'token': token}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/index/article")
async def index_article(payload: dict) -> dict:
    # Тело: {"title": "...", "content": "..."}
    from graph.build_graph import insert_articles
    text = f"{payload.get('title', '')}\n\n{payload.get('content', '')}"
    await insert_articles([text])
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
