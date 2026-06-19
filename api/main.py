import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rag.chain import RAGChain

app = FastAPI(title="news-rag", version="0.1.0")

_frontend = Path(__file__).parent.parent / "frontend"
if _frontend.exists():
    app.mount("/static", StaticFiles(directory=str(_frontend)), name="static")

    @app.get("/", include_in_schema=False)
    async def root():
        return FileResponse(str(_frontend / "index.html"))

_chain = RAGChain(qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"))


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


@app.post("/index/article")
async def index_article(payload: dict) -> dict:
    # Быстрый эндпоинт для добавления одной статьи в граф.
    # Чанкинг и индексация в Qdrant — отдельный пайплайн.
    # Тело: {"title": "...", "content": "..."}
    from graph.build_graph import insert_articles
    text = f"{payload.get('title', '')}\n\n{payload.get('content', '')}"
    await insert_articles([text])
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}