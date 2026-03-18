from datetime import datetime, timedelta

import httpx

from a_domain.model.market.stock import Stock
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MarketType


class TaiwanStockProvider(IStockProvider):
    """
    Fetches the full universe of stocks from the Taiwan Stock Exchange OpenAPI.
    Results are cached with a TTL since the listed stock universe rarely changes.
    """

    TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    CACHE_TTL = timedelta(hours=6)

    def __init__(self, logger: ILoggingProvider):
        self._logger = logger
        self._cache: list[Stock] = []
        self._cache_expiry: datetime = datetime.min

    async def get_all(self) -> list[Stock]:
        now = datetime.now()
        if self._cache and now < self._cache_expiry:
            self._logger.debug(f"Returning cached stock list ({len(self._cache)} stocks)")
            return self._cache

        stocks = await self._fetch_from_api()
        self._cache = stocks
        self._cache_expiry = now + self.CACHE_TTL
        return stocks

    async def get_by_id(self, stock_id: str) -> Stock | None:
        all_stocks = await self.get_all()
        for stock in all_stocks:
            if stock.stock_id == stock_id:
                return stock
        return None

    async def _fetch_from_api(self) -> list[Stock]:
        stocks: list[Stock] = []

        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            try:
                self._logger.debug("Fetching TWSE (上市) stocks...")
                twse_resp = await client.get(self.TWSE_URL)
                twse_resp.raise_for_status()

                for item in twse_resp.json():
                    if len(item.get("Code", "")) == 4:
                        stocks.append(Stock(stock_id=item["Code"], name=item.get("Name", "").strip(), market=MarketType.TWSE))

                self._logger.debug("Fetching TPEX (上櫃) stocks...")
                tpex_resp = await client.get(self.TPEX_URL)
                tpex_resp.raise_for_status()
                for item in tpex_resp.json():
                    if len(item.get("SecuritiesCompanyCode", "")) == 4:
                        stocks.append(
                            Stock(
                                stock_id=item["SecuritiesCompanyCode"],
                                name=item.get("CompanyName", "").strip(),
                                market=MarketType.TPEX,
                            )
                        )

                self._logger.success(f"Successfully loaded {len(stocks)} stocks from API.")
                return stocks

            except Exception as e:
                self._logger.error(f"Failed to fetch stock list: {e}")
                return []
