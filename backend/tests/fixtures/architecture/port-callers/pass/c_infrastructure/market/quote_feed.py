from typing import override

from a_domain.ports.market.price_provider import IPriceProvider, IQuoteFeed


class HeldQuoteFeed(IQuoteFeed):
    def __init__(self, prices: IPriceProvider) -> None:
        self._prices = prices

    @override
    async def latest(self, stock_id: str) -> float:
        return (await self._prices.fetch_history(stock_id))[-1]
