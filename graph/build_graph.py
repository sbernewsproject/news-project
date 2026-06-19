import asyncio
import os
from typing import Optional

from ragu import KnowledgeGraph, BuilderArguments, Settings, SimpleChunker
from ragu.models.embedder import EmbedderOpenAI
from ragu.models.llm import LLMOpenAI
from ragu.models.openai import CachedAsyncOpenAI
from ragu.triplet import RaguLmArtifactExtractor

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:32b")
RAGU_LM_MODEL = os.getenv("RAGU_LM_MODEL", "ragu-lm")

Settings.storage_folder = os.getenv("GRAPH_WORKING_DIR", "./ragu_working_dir")
Settings.language = "russian"

_llm: Optional[LLMOpenAI] = None
_embedder: Optional[EmbedderOpenAI] = None
_knowledge_graph: Optional[KnowledgeGraph] = None


def _client(**kw) -> CachedAsyncOpenAI:
    return CachedAsyncOpenAI(base_url=f"{OLLAMA_URL}/v1", api_key="ollama", **kw)


def _init() -> None:
    global _llm, _embedder, _knowledge_graph
    if _knowledge_graph is not None:
        return

    _llm = LLMOpenAI(
        client=_client(rate_max_simultaneous=2, cache="./llm_cache"),
        model_name=OLLAMA_MODEL,
    )
    _embedder = EmbedderOpenAI(
        client=_client(rate_max_simultaneous=10),
        model_name="bge-m3",
        dim=1024,
        batch_size=64,
    )
    ragu_lm = LLMOpenAI(
        client=_client(rate_max_simultaneous=4),
        model_name=RAGU_LM_MODEL,
    )
    _knowledge_graph = KnowledgeGraph(
        llm=_llm,
        embedder=_embedder,
        chunker=SimpleChunker(max_chunk_size=800, overlap=120), # можно исправить
        artifact_extractor=RaguLmArtifactExtractor(llm=ragu_lm, temperature=0.0), # тут тоже можно потестировать
        builder_settings=BuilderArguments(
            use_llm_summarization=True, # информацию объединяет в один ответ
            use_clustering=True, # группирует сущности в сообщества
            make_community_summary=True, # пишет сводку по каждому сообществу
            remove_isolated_nodes=True, # удаляет сущности без связей, чистит граф
        ),
    )


def get_knowledge_graph() -> KnowledgeGraph:
    _init()
    return _knowledge_graph


def get_llm() -> LLMOpenAI:
    _init()
    return _llm


def get_embedder() -> EmbedderOpenAI:
    _init()
    return _embedder


async def insert_articles(texts: list[str]) -> None:
    """Загружает полные тексты статей в граф. Повторный вызов безопасен - дубли пропускаются."""
    await get_knowledge_graph().build_from_docs(texts)


# CLI: python -m graph.build_graph
async def _build_from_postgres() -> None:
    import asyncpg

    dsn = os.getenv("POSTGRES_DSN", "postgresql://news:news@localhost:5432/newsdb")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT title, content FROM articles ORDER BY published_at DESC"
        )
    finally:
        await conn.close()

    texts = [f"{r['title']}\n\n{r['content']}" for r in rows]
    print(f"Загружаем {len(texts)} статей в граф...")
    await insert_articles(texts)
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(_build_from_postgres())