# backend/src/a_domain/ports/market/social_media_provider.py

from typing import Protocol

from a_domain.model.market.article import Article


class ISocialMediaProvider(Protocol):
    """Provides recent social-market discussions."""

    async def fetch_social_articles(self, limit: int) -> list[Article]: ...

    def save_social_media_data(self, articles: list[Article]) -> None:
        """Saves fetched social articles as a Markdown file."""
        ...
