import asyncio
import math
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple, override

import httpx

from a_domain.model.fundamentals.eps import Eps
from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.daily_close_archive import ExchangeNews, FinancialReport, ValuationRatios
from a_domain.ports.market.taiwan_stock_provider import ITaiwanStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import ContentType, EpsBasis, EpsKind, FinancialStatement, IndustryFormat, InformationSource, MarketType
from a_domain.types.values import FiscalQuarter
from b_application.config.market_data_config import MarketDataConfig
from b_application.config.sources_config import ExchangeSources

ROC_YEAR_OFFSET = 1911
STOCK_CODE_LENGTH = 4


class ListingFields(NamedTuple):
    """Where one exchange's daily-quotes listing keeps a stock's code, name and daily bar with its change."""

    code: str
    name: str
    bar: tuple[str, str, str, str, str, str, str]


LISTING_FIELDS = {
    MarketType.TWSE: ListingFields(
        "Code", "Name", ("Date", "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume", "Change")
    ),
    MarketType.TPEX: ListingFields(
        "SecuritiesCompanyCode", "CompanyName", ("Date", "Open", "High", "Low", "Close", "TradingShares", "Change")
    ),
}


class TaiwanStockProvider(ITaiwanStockProvider):
    """
    Fetches the full universe of stocks from the TWSE and TPEX OpenAPI.
    Results are cached with a TTL since the listed stock universe rarely changes.
    The same listings carry each stock's latest official close, cached with the universe. The company profiles'
    industries are cached in memory per market. The other reports are read as served at each call.

    Every call returns new Stock objects. Workflows fill a Stock with articles, prices and reports,
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
        # Reads that find the list empty or expired at once wait for one download instead of each downloading it.
        self._listing_lock = asyncio.Lock()
        self._industry_max_age = timedelta(hours=exchange.industry_max_age_hours)
        self._industries: dict[MarketType, dict[str, str]] = {}
        self._industries_fetched_at: dict[MarketType, datetime] = {}

    @override
    async def get_all(self) -> list[Stock]:
        stocks = await self.cached_stocks()
        return [deepcopy(stock) for stock in stocks]

    @override
    async def get_by_id(self, stock_id: str) -> Stock | None:
        for stock in await self.cached_stocks():
            if stock.stock_id == stock_id:
                return deepcopy(stock)
        return None

    @override
    async def get_latest_closes(self) -> dict[str, Ohlcv]:
        await self.cached_stocks()
        return dict(self._closes)

    @override
    async def cached_stocks(self) -> list[Stock]:
        async with self._listing_lock:
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
            code = str(row.get(fields.code) or "")

            if len(code) != STOCK_CODE_LENGTH:
                continue

            stocks.append(Stock(stock_id=code, name=str(row.get(fields.name) or "").strip(), market=market))

            if (close := self.parse_daily_close(row, fields.bar)) is not None:
                closes[code] = close

        return stocks, closes

    @override
    def parse_roc_date(self, text: str) -> date:
        return date(int(text[:-4]) + ROC_YEAR_OFFSET, int(text[-4:-2]), int(text[-2:]))

    @override
    def parse_optional_roc_date(self, text: str) -> date | None:
        try:
            return self.parse_roc_date(text)
        except ValueError:
            return None

    @override
    def parse_daily_close(self, row: dict[str, Any], fields: tuple[str, str, str, str, str, str, str]) -> Ohlcv | None:
        date_field, open_field, high_field, low_field, close_field, volume_field, change_field = fields

        try:
            session = self.parse_roc_date(str(row.get(date_field, "")))
            open_, high, low, close = (
                float(str(row.get(field, "")).replace(",", "")) for field in (open_field, high_field, low_field, close_field)
            )
            volume = int(str(row.get(volume_field, "")).replace(",", ""))
        except ValueError:
            return None

        if not all(math.isfinite(price) and price > 0 for price in (open_, high, low, close)):
            return None

        return Ohlcv(
            ts=self._clock.session_close(session),
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            change=self.parse_change(str(row.get(change_field, "")), close),
        )

    @override
    async def fetch_reports(self, urls: Mapping[MarketType, str]) -> dict[MarketType, list[dict[str, Any]]]:
        reports: dict[MarketType, list[dict[str, Any]]] = {}

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            for market, url in urls.items():
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    rows = response.json()

                    if not isinstance(rows, list):
                        raise ValueError(f"the report is a {type(rows).__name__}, not a list of rows")

                    reports[market] = [
                        {name: value.replace("\x00", "") if isinstance(value, str) else value for name, value in row.items()}
                        for row in rows
                        if isinstance(row, dict)
                    ]
                except Exception as error:
                    self._logger.error(f"Failed to fetch {url}: {error}")

        return reports

    @override
    async def fetch_industries(self) -> dict[str, str]:
        now = self._clock.now()
        stale = {
            market: feed.url
            for market, feed in self._exchange.company_profiles.items()
            if market not in self._industries_fetched_at or now - self._industries_fetched_at[market] >= self._industry_max_age
        }

        for market, rows in (await self.fetch_reports(stale)).items():
            self._industries[market] = self.parse_industries(rows, market)
            self._industries_fetched_at[market] = now

        return {stock_id: industry for industries in self._industries.values() for stock_id, industry in industries.items()}

    @override
    def parse_industries(self, rows: list[dict[str, Any]], market: MarketType) -> dict[str, str]:
        feed, names = self._exchange.company_profiles[market], self._exchange.industry_names
        return {
            str(row[feed.stock_id]).strip(): names[code]
            for row in rows
            if row.get(feed.stock_id) and (code := str(row.get(feed.industry, "")).strip()) in names
        }

    @override
    async def fetch_material_information(self) -> list[Article]:
        fetched_at = self._clock.now()
        reports = await self.fetch_reports({market: feed.url for market, feed in self._exchange.material_information.items()})
        return [
            announcement
            for market, rows in reports.items()
            for row in rows
            if (announcement := self.parse_announcement(row, market, fetched_at)) is not None
        ]

    @override
    def parse_announcement(self, row: dict[str, Any], market: MarketType, fetched_at: datetime) -> Article | None:
        feed = self._exchange.material_information[market]
        stock_id, time_text = str(row.get(feed.stock_id, "")).strip(), str(row.get(feed.time, "")).zfill(6)

        try:
            announced_at = self._clock.session_close(self.parse_roc_date(str(row.get(feed.date, "")))).replace(
                hour=int(time_text[:2]), minute=int(time_text[2:4]), second=int(time_text[4:])
            )
        except ValueError:
            return None

        if not stock_id:
            return None

        return Article(
            stock_id=stock_id,
            source=InformationSource.TWSE_MOPS,
            content_type=ContentType.FACT,
            title=str(row.get(feed.subject, "")),
            content=str(row.get(feed.description, "")),
            published_at=announced_at,
            fetched_at=fetched_at,
            clause=str(row.get(feed.clause, "")),
            fact_date=self.parse_optional_roc_date(str(row.get(feed.fact_date, ""))),
        )

    @override
    async def fetch_quarter_eps(self) -> dict[str, Eps]:
        reports = await self.fetch_reports({market: feed.url for market, feed in self._exchange.quarter_eps.items()})
        return {stock_id: eps for market, rows in reports.items() for stock_id, eps in self.parse_quarter_eps(rows, market).items()}

    @override
    def parse_quarter_eps(self, rows: list[dict[str, Any]], market: MarketType) -> dict[str, Eps]:
        feed, fetched_at = self._exchange.quarter_eps[market], self._clock.now()
        filed: dict[str, Eps] = {}

        for row in rows:
            stock_id = str(row.get(feed.stock_id, "")).strip()

            try:
                quarter = FiscalQuarter(int(str(row.get(feed.year, ""))) + ROC_YEAR_OFFSET, int(str(row.get(feed.quarter, ""))))
            except ValueError:
                continue

            if stock_id and (value := self.parse_number(str(row.get(feed.eps, "")))) is not None:
                filed[stock_id] = Eps(
                    value=value,
                    kind=EpsKind.CUMULATIVE,
                    period_end=quarter,
                    basis=EpsBasis.ACTUAL,
                    source=InformationSource.TWSE_MOPS,
                    fetched_at=fetched_at,
                )

        return filed

    @override
    async def fetch_valuation_ratios(self) -> list[ValuationRatios]:
        reports = await self.fetch_reports({market: feed.url for market, feed in self._exchange.valuation_ratios.items()})
        return [ratios for market, rows in reports.items() for ratios in self.parse_valuation_ratios(rows, market)]

    @override
    def parse_valuation_ratios(self, rows: list[dict[str, Any]], market: MarketType) -> list[ValuationRatios]:
        feed = self._exchange.valuation_ratios[market]
        published: list[ValuationRatios] = []

        for row in rows:
            stock_id = str(row.get(feed.stock_id, "")).strip()

            if not stock_id or (session := self.parse_optional_roc_date(str(row.get(feed.date, "")))) is None:
                continue

            published.append(
                ValuationRatios(
                    stock_id=stock_id,
                    session_date=session,
                    pe_ratio=self.parse_number(str(row.get(feed.pe_ratio, ""))),
                    dividend_yield=self.parse_number(str(row.get(feed.dividend_yield, ""))),
                    pb_ratio=self.parse_number(str(row.get(feed.pb_ratio, ""))),
                )
            )

        return published

    @override
    async def fetch_financial_reports(self) -> list[FinancialReport]:
        feeds = self._exchange.financial_reports
        reports: list[FinancialReport] = []

        for statement in FinancialStatement:
            for industry_format in IndustryFormat:
                served = await self.fetch_reports({market: urls[statement][industry_format] for market, urls in feeds.urls.items()})
                reports.extend(
                    report
                    for market, rows in served.items()
                    for row in rows
                    if (report := self.parse_financial_report(row, market, statement, industry_format)) is not None
                )

        return reports

    @override
    def parse_financial_report(
        self, row: dict[str, Any], market: MarketType, statement: FinancialStatement, industry_format: IndustryFormat
    ) -> FinancialReport | None:
        feeds = self._exchange.financial_reports
        stock_id = self.served_field(row, feeds.stock_id)

        try:
            year, quarter = (int(self.served_field(row, names)) for names in (feeds.year, feeds.quarter))
            period = FiscalQuarter(year + ROC_YEAR_OFFSET, quarter)
            served_date = self.parse_roc_date(self.served_field(row, feeds.served_date))
        except ValueError:
            return None

        if not stock_id:
            return None

        return FinancialReport(
            stock_id=stock_id,
            quarter=period,
            statement=statement,
            market=market,
            industry_format=industry_format,
            served_date=served_date,
            items={name: str(value) for name, value in row.items() if name not in feeds.identity},
        )

    @override
    def served_field(self, row: dict[str, Any], names: list[str]) -> str:
        return next((str(row[name]).strip() for name in names if name in row), "")

    @override
    async def fetch_monthly_revenues(self) -> list[MonthlyRevenue]:
        reports = await self.fetch_reports({market: feed.url for market, feed in self._exchange.monthly_revenue.items()})
        return [
            revenue
            for market, rows in reports.items()
            for row in rows
            if (revenue := self.parse_monthly_revenue(row, market)) is not None
        ]

    @override
    def parse_monthly_revenue(self, row: dict[str, Any], market: MarketType) -> MonthlyRevenue | None:
        feed = self._exchange.monthly_revenue[market]

        if not (stock_id := self.served_field(row, [feed.stock_id])):
            return None

        year_month = self.served_field(row, [feed.year_month])

        try:
            return MonthlyRevenue(
                stock_id=stock_id,
                year=int(year_month[:-2]) + ROC_YEAR_OFFSET,
                month=int(year_month[-2:]),
                market=market,
                served_date=self.parse_roc_date(self.served_field(row, [feed.served_date])),
                company_name=self.served_field(row, [feed.company_name]),
                industry=self.served_field(row, [feed.industry]),
                revenue=self.parse_number(self.served_field(row, [feed.revenue])),
                previous_month_revenue=self.parse_number(self.served_field(row, [feed.previous_month_revenue])),
                last_year_revenue=self.parse_number(self.served_field(row, [feed.last_year_revenue])),
                month_over_month_percent=self.parse_number(self.served_field(row, [feed.month_over_month_percent])),
                year_over_year_percent=self.parse_number(self.served_field(row, [feed.year_over_year_percent])),
                cumulative_revenue=self.parse_number(self.served_field(row, [feed.cumulative_revenue])),
                last_year_cumulative_revenue=self.parse_number(self.served_field(row, [feed.last_year_cumulative_revenue])),
                cumulative_year_over_year_percent=self.parse_number(self.served_field(row, [feed.cumulative_year_over_year_percent])),
                note=self.served_field(row, [feed.note]),
            )
        except ValueError:
            return None

    @override
    async def fetch_exchange_news(self) -> list[ExchangeNews]:
        reports = await self.fetch_reports({MarketType.TWSE: self._exchange.exchange_news.url})
        return [news for rows in reports.values() for row in rows if (news := self.parse_exchange_news(row)) is not None]

    @override
    def parse_exchange_news(self, row: dict[str, Any]) -> ExchangeNews | None:
        feed = self._exchange.exchange_news
        url = self.served_field(row, [feed.link])

        if not url or (published_on := self.parse_optional_roc_date(self.served_field(row, [feed.date]))) is None:
            return None

        return ExchangeNews(url=url, title=self.served_field(row, [feed.title]), published_on=published_on)

    @override
    def parse_number(self, text: str) -> float | None:
        try:
            value = float(text.replace(",", ""))
        except ValueError:
            return None

        return value if math.isfinite(value) else None

    @override
    async def fetch_index_closes(self) -> dict[MarketType, list[Ohlcv]]:
        parsers = {MarketType.TWSE: self.parse_twse_index, MarketType.TPEX: self.parse_tpex_index}
        reports = await self.fetch_reports(
            {MarketType.TWSE: self._exchange.twse_index_url, MarketType.TPEX: self._exchange.tpex_index_url}
        )
        return {market: parsers[market](rows) for market, rows in reports.items()}

    @override
    def parse_twse_index(self, rows: list[dict[str, Any]]) -> list[Ohlcv]:
        fields = self._exchange.twse_index_fields
        closes: list[Ohlcv] = []

        for row in rows:
            if row.get(fields.index) != fields.taiex:
                continue

            try:
                session = self.parse_roc_date(str(row.get(fields.date, "")))
            except ValueError:
                continue

            sign = "-" if row.get(fields.sign) == "-" else ""
            close_text, change_text = str(row.get(fields.close, "")), sign + str(row.get(fields.change, ""))

            if (close := self.parse_index_close(session, close_text, change_text)) is not None:
                closes.append(close)

        return closes

    @override
    def parse_tpex_index(self, rows: list[dict[str, Any]]) -> list[Ohlcv]:
        closes: list[Ohlcv] = []

        for row in rows:
            try:
                session = date.fromisoformat(str(row.get("Date", "")))
            except ValueError:
                continue

            if (close := self.parse_index_close(session, str(row.get("Close", "")), str(row.get("Change", "")))) is not None:
                closes.append(close)

        return closes

    @override
    def parse_index_close(self, session: date, close_text: str, change_text: str) -> Ohlcv | None:
        try:
            close = float(close_text.replace(",", ""))
        except ValueError:
            return None

        if not (math.isfinite(close) and close > 0):
            return None

        return Ohlcv(ts=self._clock.session_close(session), close=close, change=self.parse_change(change_text, close))

    @override
    def parse_change(self, text: str, close: float) -> float | None:
        try:
            change = float(text.replace(",", ""))
        except ValueError:
            return None

        return change if math.isfinite(change) and close - change > 0 else None
