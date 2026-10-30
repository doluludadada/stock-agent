import math
from datetime import date, datetime, timedelta

import httpx

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MarketType
from c_infrastructure.system.market_clock import TAIWAN_SESSION_CLOSE, TAIWAN_TIMEZONE

ROC_YEAR_OFFSET = 1911

TWSE_BAR_FIELDS = ("Date", "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume")
TPEX_BAR_FIELDS = ("Date", "Open", "High", "Low", "Close", "TradingShares")


def parse_roc_date(text: str) -> date:
    """'1151029' (ROC year 115) is 2026-10-29."""
    return date(int(text[:-4]) + ROC_YEAR_OFFSET, int(text[-4:-2]), int(text[-2:]))


def parse_daily_close(row: dict[str, str], fields: tuple[str, str, str, str, str, str]) -> Ohlcv | None:
    """The row's official daily bar, or None when the stock did not trade (TWSE leaves prices blank, TPEX writes '---')."""
    date_field, open_field, high_field, low_field, close_field, volume_field = fields

    try:
        session = parse_roc_date(row.get(date_field, ""))
        open_, high, low, close = (
            float(row.get(field, "").replace(",", "")) for field in (open_field, high_field, low_field, close_field)
        )
        volume = int(row.get(volume_field, "").replace(",", ""))
    except ValueError:
        return None

    if not all(math.isfinite(price) and price > 0 for price in (open_, high, low, close)):
        return None

    return Ohlcv(
        ts=datetime.combine(session, TAIWAN_SESSION_CLOSE, TAIWAN_TIMEZONE), open=open_, high=high, low=low, close=close, volume=volume
    )


class TaiwanStockProvider(IStockProvider):
    """
    Fetches the full universe of stocks from the Taiwan Stock Exchange OpenAPI.
    Results are cached with a TTL since the listed stock universe rarely changes.
    The same listings carry each stock's latest official close, cached with the universe.

    Every call returns new Stock and Ohlcv objects. Workflows fill a Stock with articles, prices and reports,
    so handing out the cached instances would carry one workflow's data into the next.
    """

    TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    CACHE_TTL = timedelta(hours=6)

    def __init__(self, logger: ILoggingProvider):
        self._logger = logger
        self._cache: list[Stock] = []
        self._closes: dict[str, Ohlcv] = {}
        self._cache_expiry: datetime = datetime.min

    async def get_all(self) -> list[Stock]:
        stocks = await self._cached_stocks()
        return [stock.model_copy(deep=True) for stock in stocks]

    async def get_by_id(self, stock_id: str) -> Stock | None:
        for stock in await self._cached_stocks():
            if stock.stock_id == stock_id:
                return stock.model_copy(deep=True)
        return None

    async def _cached_stocks(self) -> list[Stock]:
        now = datetime.now()
        if self._cache and now < self._cache_expiry:
            self._logger.debug(f"Returning cached stock list ({len(self._cache)} stocks)")
            return self._cache

        self._cache, self._closes = await self._fetch_from_api()
        self._cache_expiry = now + self.CACHE_TTL
        return self._cache

    async def get_latest_closes(self) -> dict[str, Ohlcv]:
        await self._cached_stocks()
        return {stock_id: close.model_copy() for stock_id, close in self._closes.items()}

    async def _fetch_from_api(self) -> tuple[list[Stock], dict[str, Ohlcv]]:
        stocks: list[Stock] = []
        closes: dict[str, Ohlcv] = {}

        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            try:
                self._logger.debug("Fetching TWSE (上市) stocks...")
                twse_resp = await client.get(self.TWSE_URL)
                twse_resp.raise_for_status()

                for item in twse_resp.json():
                    if len(item.get("Code", "")) == 4:
                        stocks.append(Stock(stock_id=item["Code"], name=item.get("Name", "").strip(), market=MarketType.TWSE))
                        if (close := parse_daily_close(item, TWSE_BAR_FIELDS)) is not None:
                            closes[item["Code"]] = close

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
                        if (close := parse_daily_close(item, TPEX_BAR_FIELDS)) is not None:
                            closes[item["SecuritiesCompanyCode"]] = close

                self._logger.success(f"Successfully loaded {len(stocks)} stocks and {len(closes)} daily closes from API.")
                return stocks, closes

            except Exception as e:
                self._logger.error(f"Failed to fetch stock list: {e}")
                return [], {}
