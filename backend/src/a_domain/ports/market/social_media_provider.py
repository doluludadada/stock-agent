from typing import Protocol

from a_domain.model.market.stock import Stock


class ISocialMediaProvider(Protocol):
    """(Hot Data) Fetches trending stocks from Social Media/News."""

    # TODO: I think it should also return Article not Stock? idk
    async def get_trending_stocks(self, limit: int) -> list[Stock]:
        """
        Returns a list of Stock entities.
        The implementation should set `stock.stock_id`, `stock.source = CandidateSource.SOCIAL_BUZZ`,
        and populate `stock.trigger_reason`.
        """
        ...
