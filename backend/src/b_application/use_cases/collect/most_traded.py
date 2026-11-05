from a_domain.model.market.stock import Stock
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.rules.market.listing import MostTradedRule
from a_domain.types.errors import ListingUnavailableError
from b_application.config.app_config import AppConfig


class MostTraded:
    """The latest session's most traded stocks in the exchange listing, each with that session's official daily bar."""

    def __init__(self, stock_provider: IStockProvider, config: AppConfig) -> None:
        self._stock_provider = stock_provider
        self._most_traded_rule = MostTradedRule(limit=config.market_data.most_traded_count)

    async def execute(self) -> list[Stock]:
        closes = await self._stock_provider.get_latest_closes()
        stocks = {stock.stock_id: stock for stock in await self._stock_provider.get_all()}

        if not stocks:
            raise ListingUnavailableError("The TWSE and TPEX listings could not be loaded.")

        ranked = [stocks[stock_id] for stock_id in self._most_traded_rule.apply(closes) if stock_id in stocks]

        for stock in ranked:
            stock.load_history([closes[stock.stock_id]])

        return ranked
