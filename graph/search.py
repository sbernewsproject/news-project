"""
Интерфейс поиска по графу знаний через LightRAG.
  global_search — сводки по сообществам (широкие тематические запросы)
  local_search  — контекст на уровне сущностей (запросы о конкретных объектах)
"""

from lightrag import QueryParam

from .build_graph import get_rag


async def global_search(query: str) -> str:
    """Сводки по сообществам. Подходит для вопросов о трендах и ситуации в целом."""
    return await get_rag().aquery(query, param=QueryParam(mode="global"))


async def local_search(query: str) -> str:
    """Контекст сущностей и связей. Подходит для вопросов о конкретных компаниях/персонах."""
    return await get_rag().aquery(query, param=QueryParam(mode="local"))