import math
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple, override

import httpx

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.taiwan_stock_provider import ITaiwanStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import MarketType
from b_application.config.market_data_config import MarketDataConfig
from b_application.config.sources_config import ExchangeSources

ROC_YEAR_OFFSET = 1911
STOCK_CODE_LENGTH = 4


class ListingFields(NamedTuple):
    """Where one exchange's daily-quotes listing keeps a stock's code, name and daily bar."""

    code: str
    name: str
    bar: tuple[str, str, str, str, str, str]


LISTING_FIELDS = {
    MarketType.TWSE: ListingFields(
        "Code", "Name", ("Date", "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume")
    ),
    MarketType.TPEX: ListingFields("SecuritiesCompanyCode", "CompanyName", ("Date", "Open", "High", "Low", "Close", "TradingShares")),
}


class TaiwanStockProvider(ITaiwanStockProvider):
    """
    Fetches the full universe of stocks from the Taiwan Stock Exchange OpenAPI.
    Results are cached with a TTL since the listed stock universe rarely changes.
    The same listings carry each stock's latest official close, cached with the universe.

    Every call returns new Stock and Ohlcv objects. Workflows fill a Stock with articles, prices and reports,
    so handing out the cached instances would carry one workflow's data into the next.
    """

    def __init__(self, exchange: ExchangeSources, market_clock: IMarketClock, market_data: MarketDataConfig, logger: ILoggingProvider):
        self._exchange = exchange
        self._clock = market_clock
        self._cache_ttl = timedelta(hours=market_data.listing_cache_hours)
        self._timeout_seconds = market_data.listing_timeout_seconds
        self._logger = logger
        self._cache: list[Stock] = []
        self._closes: dict[str, Ohlcv] = {}
        self._cache_expiry = datetime.min.replace(tzinfo=UTC)

    @override
    async def get_all(self) -> list[Stock]:
        stocks = await self.cached_stocks()
        return [stock.model_copy(deep=True) for stock in stocks]

    @override
    async def get_by_id(self, stock_id: str) -> Stock | None:
        for stock in await self.cached_stocks():
            if stock.stock_id == stock_id:
                return stock.model_copy(deep=True)
        return None

    @override
    async def get_latest_closes(self) -> dict[str, Ohlcv]:
        await self.cached_stocks()
        return {stock_id: close.model_copy() for stock_id, close in self._closes.items()}

    @override
    async def cached_stocks(self) -> list[Stock]:
        now = self._clock.now()
        if self._cache and now < self._cache_expiry:
            self._logger.debug(f"Returning cached stock list ({len(self._cache)} stocks)")
            return self._cache

        self._cache, self._closes = await self.fetch_listings()
        self._cache_expiry = now + self._cache_ttl
        return self._cache

    @override
    async def fetch_listings(self) -> tuple[list[Stock], dict[str, Ohlcv]]:
        stocks: list[Stock] = []
        closes: dict[str, Ohlcv] = {}

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            try:
                for market, url in (
                    (MarketType.TWSE, self._exchange.twse_daily_quotes_url),
                    (MarketType.TPEX, self._exchange.tpex_daily_quotes_url),
                ):
                    self._logger.debug(f"Fetching {market} stocks...")
                    response = await client.get(url)
                    response.raise_for_status()
                    listed, listed_closes = self.parse_listing(response.json(), market)
                    stocks.extend(listed)
                    closes.update(listed_closes)

                self._logger.success(f"Successfully loaded {len(stocks)} stocks and {len(closes)} daily closes from API.")
                return stocks, closes

            except Exception as error:
                self._logger.error(f"Failed to fetch stock list: {error}")
                return [], {}

    @override
    def parse_listing(self, rows: list[dict[str, Any]], market: MarketType) -> tuple[list[Stock], dict[str, Ohlcv]]:
        fields = LISTING_FIELDS[market]
        stocks: list[Stock] = []
        closes: dict[str, Ohlcv] = {}

        for row in rows:
            code = row.get(fields.code, "")

            if len(code) != STOCK_CODE_LENGTH:
                continue

            stocks.append(Stock(stock_id=code, name=row.get(fields.name, "").strip(), market=market))

            if (close := self.parse_daily_close(row, fields.bar)) is not None:
                closes[code] = close

        return stocks, closes

    @override
    def parse_roc_date(self, text: str) -> date:
        return date(int(text[:-4]) + ROC_YEAR_OFFSET, int(text[-4:-2]), int(text[-2:]))

    @override
    def parse_daily_close(self, row: dict[str, Any], fields: tuple[str, str, str, str, str, str]) -> Ohlcv | None:
        date_field, open_field, high_field, low_field, close_field, volume_field = fields

        try:
            session = self.parse_roc_date(row.get(date_field, ""))
            open_, high, low, close = (
                float(row.get(field, "").replace(",", "")) for field in (open_field, high_field, low_field, close_field)
            )
            volume = int(row.get(volume_field, "").replace(",", ""))
        except ValueError:
            return None

        if not all(math.isfinite(price) and price > 0 for price in (open_, high, low, close)):
            return None

        return Ohlcv(ts=self._clock.session_close(session), open=open_, high=high, low=low, close=close, volume=volume)
