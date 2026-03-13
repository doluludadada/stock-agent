# backend/src/c_infrastructure/market/taiwan_stock_provider.py
import httpx

from a_domain.model.market.stock import Stock
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MarketType


class TaiwanStockProvider(IStockProvider):
    """
    Fetches the full universe of stocks from the Taiwan Stock Exchange OpenAPI.
    """

    TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

    def __init__(self, logger: ILoggingProvider):
        self._logger = logger

    async def get_all(self) -> list[Stock]:
        stocks: list[Stock] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                self._logger.debug("Fetching TWSE (上市) stocks...")
                twse_resp = await client.get(self.TWSE_URL)
                twse_resp.raise_for_status()

                for item in twse_resp.json():
                    if len(item.get("Code", "")) == 4:
                        stocks.append(
                            Stock(stock_id=item["Code"], name=item.get("Name", "").strip(), market=MarketType.TWSE)
                        )

                self._logger.debug("Fetching TPEX (上櫃) stocks...")
                tpex_resp = await client.get(self.TPEX_URL)
                tpex_resp.raise_for_status()
                # TODO: This hard code looks weird
                for item in tpex_resp.json():
                    if len(item.get("SecuritiesCompanyCode", "")) == 4:
                        stocks.append(
                            Stock(
                                stock_id=item["SecuritiesCompanyCode"],
                                name=item.get("CompanyName", "").strip(),
                                market=MarketType.TPEX,
                            )
                        )

                self._logger.success(f"Successfully loaded {len(stocks)} stocks.")
                return stocks

            except Exception as e:
                self._logger.error(f"Failed to fetch stock list: {e}")
                return []

    async def get_by_id(self, stock_id: str) -> Stock | None:
        """Fallback to filtering the full list if a specific stock is requested."""
        # Is it the best way to get
        all_stocks = await self.get_all()
        for stock in all_stocks:
            if stock.stock_id == stock_id:
                return stock
        return None
