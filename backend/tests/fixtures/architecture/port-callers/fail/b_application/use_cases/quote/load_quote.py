from a_domain.ports.market.price_provider import IPriceProvider


class LoadQuote:
    def __init__(self, prices: IPriceProvider) -> None:
        self._prices = prices

    async def execute(self, stock_id: str) -> float:
        return await self._prices.fetch(stock_id)
