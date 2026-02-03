from typing import Protocol


class ISocialMediaProvider(Protocol):
    """(Hot Data) Interface to fetch trending stocks from Social Media/News."""

    async def get_trending_stocks(self, limit: int = 10) -> list[tuple[str, str]]:
        """
        Returns: list of (stock_id, reason)
        Example: [("2330", "PTT mentions > 50"), ("2317", "News Volume Spike")]
        """
        ...


