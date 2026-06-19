from ragu import GlobalSearchEngine
from ragu.search_engine.local_search import LocalSearchEngine

from .build_graph import get_embedder, get_knowledge_graph, get_llm


async def local_search(query: str) -> str:
    """Поиск по сущностям и связям. Для вопросов о конкретных компаниях/персонах."""
    engine = LocalSearchEngine(
        llm=get_llm(),
        knowledge_graph=get_knowledge_graph(),
        embedder=get_embedder(),
    )
    result = await engine.a_query(query, use_summary=True, use_chunks=True)
    return result.response


async def global_search(query: str) -> str:
    """Поиск по сводкам сообществ. Для вопросов о трендах и ситуации в целом."""
    engine = GlobalSearchEngine(
        llm=get_llm(),
        knowledge_graph=get_knowledge_graph(),
    )
    result = await engine.a_query(query)
    return result.response