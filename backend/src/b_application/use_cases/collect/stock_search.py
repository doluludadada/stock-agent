from a_domain.model.market.stock import Stock
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.rules.market.listing import StockSearchRule
from a_domain.types.errors import ListingUnavailableError
from b_application.config.app_config import AppConfig


class StockSearch:
    """Finds listed stocks by code or name in the exchange listing; each comes with its latest official close, if it traded."""

    def __init__(self, stock_provider: IStockProvider, config: AppConfig) -> None:
        self._stock_provider = stock_provider
        self._search_rule = StockSearchRule(limit=config.market_data.search_result_limit)

    async def execute(self, query: str) -> list[Stock]:
        listing = await self._stock_provider.get_all()

        if not listing:
            raise ListingUnavailableError("The TWSE and TPEX listings could not be loaded.")

        matches = self._search_rule.apply(listing, query)
        closes = await self._stock_provider.get_latest_closes()

        for stock in matches:
            stock.load_history([closes[stock.stock_id]] if stock.stock_id in closes else [])

        return matches
