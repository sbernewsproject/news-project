import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api.articles import router as articles_router
from api.db import close_pool, init_pool

# Адрес RAG-сервиса на GPU-хосте. Если задан — /query проксируется туда, и этот
# (лёгкий) образ для VPS не тянет torch/sentence-transformers в процесс.
RAG_URL = os.getenv("RAG_URL")

_chain = None  # локальная RAG-цепочка (ленивая, только если RAG_URL не задан)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="news-api", version="0.1.0", lifespan=lifespan)
app.include_router(articles_router)

_frontend = Path(__file__).parent.parent / "frontend"
if _frontend.exists():
    app.mount("/static", StaticFiles(directory=str(_frontend)), name="static")

    @app.get("/", include_in_schema=False)
    async def root():
        return FileResponse(str(_frontend / "index.html"))


class QueryRequest(BaseModel):
    query: str
    top_k: int = 10


class QueryResponse(BaseModel):
    answer: str
    route: Optional[str] = None


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    # Режим VPS: проксируем запрос на RAG-сервис GPU-хоста.
    if RAG_URL:
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(f"{RAG_URL}/query", json=req.model_dump())
                resp.raise_for_status()
                return QueryResponse(**resp.json())
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"RAG-сервис недоступен: {e}")

    # Локальный режим (всё в одном процессе): ленивый импорт, чтобы лёгкий образ
    # без RAG_URL не падал на отсутствии torch, пока /query не вызван.
    global _chain
    try:
        from rag.chain import RAGChain, _route
        if _chain is None:
            _chain = RAGChain(
                qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
                api_key=os.getenv("QDRANT_API_KEY"),
            )
        result = await _chain.answer(req.query, top_k=req.top_k)
        return QueryResponse(answer=result, route=_route(req.query))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/index/article")
async def index_article(payload: dict) -> dict:
    # Быстрый эндпоинт для добавления одной статьи в граф (нужны graph-зависимости).
    # Тело: {"title": "...", "content": "..."}
    from graph.build_graph import insert_articles
    text = f"{payload.get('title', '')}\n\n{payload.get('content', '')}"
    await insert_articles([text])
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
