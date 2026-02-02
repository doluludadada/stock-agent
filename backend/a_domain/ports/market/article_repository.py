# src/a_domain/ports/market/article_repository.py
from typing import Protocol

from src.a_domain.model.market.article import Article


class IArticleRepository(Protocol):
    async def get_by_stock_id(self, stock_id: str, limit: int = 10) -> list[Article]: ...
    async def save(self, articles: list[Article]) -> None: ...
