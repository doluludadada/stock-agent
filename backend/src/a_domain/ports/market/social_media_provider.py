from typing import Protocol

from a_domain.model.market.article import Article


class ISocialMediaProvider(Protocol):
    """(Hot Data) Fetches trending stocks from Social Media/News."""

    async def get_trending_stocks(self, limit: int) -> list[Article]:
        """
        Returns a list of Article entities representing trending topics.
        """
        ...

    def save_social_media_data(self, articles: list[Article]) -> None:
        """Saves fetched trending articles as a Markdown file."""
        ...
