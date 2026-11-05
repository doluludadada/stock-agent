from a_domain.model.market.stock import Stock
from a_domain.ports.market.stock_provider import IStockProvider


class OfficialChangeFeed:
    """
    Puts the exchange's official change of the latest session on each stock's daily bar of that session. Only the TWSE
    and TPEX listings report it, against the session's reference price; the daily history does not.
    """

    def __init__(self, stock_provider: IStockProvider) -> None:
        self._stock_provider = stock_provider

    async def execute(self, stocks: list[Stock]) -> list[Stock]:
        closes = await self._stock_provider.get_latest_closes()

        for stock in stocks:
            if (close := closes.get(stock.stock_id)) is not None:
                stock.take_official_change(close)

        return stocks
