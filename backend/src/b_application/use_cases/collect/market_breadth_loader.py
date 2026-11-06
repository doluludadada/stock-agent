from a_domain.ports.market.taiwan_stock_provider import ITaiwanStockProvider
from a_domain.rules.market.breadth import MarketBreadth, MarketBreadthRule
from a_domain.types.errors import ListingUnavailableError


class MarketBreadthLoader:
    """The latest session's advancers, decliners and unchanged stocks in the exchange listing, overall and per industry."""

    def __init__(self, stock_provider: ITaiwanStockProvider) -> None:
        self._stock_provider = stock_provider
        self._breadth_rule = MarketBreadthRule()

    async def execute(self) -> MarketBreadth:
        closes = await self._stock_provider.get_latest_closes()
        breadth = self._breadth_rule.apply(closes, await self._stock_provider.fetch_industries())

        if breadth is None:
            raise ListingUnavailableError("The TWSE and TPEX listings could not be loaded.")

        return breadth
