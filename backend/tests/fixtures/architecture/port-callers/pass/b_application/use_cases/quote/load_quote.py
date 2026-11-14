from a_domain.ports.market.price_provider import IPriceProvider, IQuoteFeed


class LoadQuote:
    def __init__(self, prices: IPriceProvider, feed: IQuoteFeed) -> None:
        self._prices = prices
        self._feed = feed

    async def execute(self, stock_id: str) -> float:
        return await self._prices.fetch(stock_id) or await self._feed.latest(stock_id)
