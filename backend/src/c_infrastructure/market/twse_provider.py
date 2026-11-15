import asyncio
from collections.abc import Callable, Collection, Mapping
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple, override

import httpx

from a_domain.model.fundamentals.eps import Eps
from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.market.article import Article
from a_domain.model.market.company_profile import CompanyProfile
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
from c_infrastructure.market.exchange_text import (
    ROC_YEAR_OFFSET,
    parse_change,
    parse_number,
    parse_optional_date,
    parse_optional_roc_date,
    parse_roc_date,
    web_address,
)

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

            self._cache, self._closes = await fetch_listings(self._exchange, self._clock, self._timeout_seconds, self._logger)
            self._cache_expiry = now + self._cache_ttl
            return self._cache

    @override
    async def fetch_industries(self) -> dict[str, str]:
        now = self._clock.now()
        stale = {
            market: feed.url
            for market, feed in self._exchange.company_profiles.items()
            if market not in self._industries_fetched_at or now - self._industries_fetched_at[market] >= self._industry_max_age
        }

        for market, rows in (await fetch_reports(stale, self._timeout_seconds, self._logger)).items():
            self._industries[market] = parse_industries(rows, market, self._exchange)
            self._industries_fetched_at[market] = now

        return {stock_id: industry for industries in self._industries.values() for stock_id, industry in industries.items()}

    @override
    async def fetch_company_profiles(self) -> list[CompanyProfile]:
        fetched_at = self._clock.now()
        reports = await read_reports(
            {market: feed.url for market, feed in self._exchange.company_profiles.items()},
            lambda rows, market: [
                profile for row in rows if (profile := parse_company_profile(row, market, self._exchange, fetched_at)) is not None
            ],
            self._timeout_seconds,
            self._logger,
        )
        return [profile for profiles in reports.values() for profile in profiles]

    @override
    async def fetch_material_information(self) -> list[Article]:
        fetched_at = self._clock.now()
        reports = await read_reports(
            {market: feed.url for market, feed in self._exchange.material_information.items()},
            lambda rows, market: [
                announcement
                for row in rows
                if (announcement := parse_announcement(row, market, fetched_at, self._exchange, self._clock)) is not None
            ],
            self._timeout_seconds,
            self._logger,
        )
        return [announcement for announcements in reports.values() for announcement in announcements]

    @override
    async def fetch_quarter_eps(self) -> dict[str, Eps]:
        reports = await read_reports(
            {market: feed.url for market, feed in self._exchange.quarter_eps.items()},
            lambda rows, market: parse_quarter_eps(rows, market, self._exchange, self._clock),
            self._timeout_seconds,
            self._logger,
        )
        return {stock_id: eps for filed in reports.values() for stock_id, eps in filed.items()}

    @override
    async def fetch_valuation_ratios(self) -> list[ValuationRatios]:
        reports = await read_reports(
            {market: feed.url for market, feed in self._exchange.valuation_ratios.items()},
            lambda rows, market: parse_valuation_ratios(rows, market, self._exchange),
            self._timeout_seconds,
            self._logger,
        )
        return [ratios for published in reports.values() for ratios in published]

    @override
    async def fetch_financial_reports(self) -> list[FinancialReport]:
        feeds = self._exchange.financial_reports
        reports: list[FinancialReport] = []

        empty: list[str] = []

        for statement in FinancialStatement:
            for industry_format in IndustryFormat:
                urls = {market: by_statement[statement][industry_format] for market, by_statement in feeds.urls.items()}

                for market, rows in (await fetch_reports(urls, self._timeout_seconds, self._logger)).items():
                    filed = [
                        report
                        for row in rows
                        if (report := parse_financial_report(row, market, statement, industry_format, self._exchange)) is not None
                    ]
                    reports.extend(filed)

                    if not filed and not served_rows(rows):
                        empty.append(urls[market])
                    else:
                        log_unread(urls[market], rows, len(filed), self._logger)

        if empty:
            self._logger.info(f"{len(empty)} financial report feeds served no rows: {', '.join(empty)}")

        return reports

    @override
    async def fetch_monthly_revenues(self) -> list[MonthlyRevenue]:
        reports = await read_reports(
            {market: feed.url for market, feed in self._exchange.monthly_revenue.items()},
            lambda rows, market: [revenue for row in rows if (revenue := self.parse_monthly_revenue(row, market)) is not None],
            self._timeout_seconds,
            self._logger,
        )
        return [revenue for revenues in reports.values() for revenue in revenues]

    @override
    def parse_monthly_revenue(self, row: dict[str, Any], market: MarketType) -> MonthlyRevenue | None:
        feed = self._exchange.monthly_revenue[market]

        if not (stock_id := served_field(row, [feed.stock_id])):
            return None

        year_month = "".join(part.zfill(2) for part in served_field(row, [feed.year_month]).split("/"))
        served = "".join(part.zfill(2) for part in served_field(row, [feed.served_date]).split("/"))

        try:
            return MonthlyRevenue(
                stock_id=stock_id,
                year=int(year_month[:-2]) + ROC_YEAR_OFFSET,
                month=int(year_month[-2:]),
                market=market,
                served_date=parse_roc_date(served),
                company_name=served_field(row, [feed.company_name]),
                industry=served_field(row, [feed.industry]),
                revenue=parse_number(served_field(row, [feed.revenue])),
                previous_month_revenue=parse_number(served_field(row, [feed.previous_month_revenue])),
                last_year_revenue=parse_number(served_field(row, [feed.last_year_revenue])),
                month_over_month_percent=parse_number(served_field(row, [feed.month_over_month_percent])),
                year_over_year_percent=parse_number(served_field(row, [feed.year_over_year_percent])),
                cumulative_revenue=parse_number(served_field(row, [feed.cumulative_revenue])),
                last_year_cumulative_revenue=parse_number(served_field(row, [feed.last_year_cumulative_revenue])),
                cumulative_year_over_year_percent=parse_number(served_field(row, [feed.cumulative_year_over_year_percent])),
                note=served_field(row, [feed.note]),
            )
        except ValueError:
            return None

    @override
    async def fetch_exchange_news(self) -> list[ExchangeNews]:
        reports = await read_reports(
            {MarketType.TWSE: self._exchange.exchange_news.url},
            lambda rows, market: [news for row in rows if (news := parse_exchange_news(row, self._exchange)) is not None],
            self._timeout_seconds,
            self._logger,
        )
        return [news for items in reports.values() for news in items]

    @override
    async def fetch_index_closes(self) -> dict[MarketType, list[Ohlcv]]:
        return await read_reports(
            {MarketType.TWSE: self._exchange.twse_index_url, MarketType.TPEX: self._exchange.tpex_index_url},
            lambda rows, market: (
                parse_twse_index(rows, self._exchange, self._clock)
                if market == MarketType.TWSE
                else parse_tpex_index(rows, self._clock)
            ),
            self._timeout_seconds,
            self._logger,
        )


async def fetch_listings(
    exchange: ExchangeSources, clock: IMarketClock, timeout_seconds: float, logger: ILoggingProvider
) -> tuple[list[Stock], dict[str, Ohlcv]]:
    """Both listings' stocks and their closes. A failed fetch is logged and yields neither."""
    stocks: list[Stock] = []
    closes: dict[str, Ohlcv] = {}

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            for market, url in ((MarketType.TWSE, exchange.twse_daily_quotes_url), (MarketType.TPEX, exchange.tpex_daily_quotes_url)):
                logger.debug(f"Fetching {market} stocks...")
                response = await client.get(url)
                response.raise_for_status()
                rows = response.json()
                listed, listed_closes = parse_listing(rows, market, clock)
                log_unread(url, rows, len(listed_closes), logger)
                stocks.extend(listed)
                closes.update(listed_closes)

            logger.success(f"Successfully loaded {len(stocks)} stocks and {len(closes)} daily closes from API.")
            return stocks, closes

        except Exception as error:
            logger.error(f"Failed to fetch stock list: {error}")
            return [], {}


def parse_listing(rows: list[dict[str, Any]], market: MarketType, clock: IMarketClock) -> tuple[list[Stock], dict[str, Ohlcv]]:
    """The stocks with a four-digit code in one exchange's listing, and the official close of each that traded."""
    fields = LISTING_FIELDS[market]
    stocks: list[Stock] = []
    closes: dict[str, Ohlcv] = {}

    for row in rows:
        code = str(row.get(fields.code) or "")

        if len(code) != STOCK_CODE_LENGTH:
            continue

        stocks.append(Stock(stock_id=code, name=str(row.get(fields.name) or "").strip(), market=market))

        if (close := parse_daily_close(row, fields.bar, clock)) is not None:
            closes[code] = close

    return stocks, closes


def parse_daily_close(row: dict[str, Any], fields: tuple[str, str, str, str, str, str, str], clock: IMarketClock) -> Ohlcv | None:
    """
    The row's official daily bar with its change, or None when the stock did not trade (TWSE leaves prices blank,
    TPEX writes '---').
    """
    date_field, open_field, high_field, low_field, close_field, volume_field, change_field = fields

    open_, high, low, close = (
        parse_number(str(row.get(field, ""))) or 0.0 for field in (open_field, high_field, low_field, close_field)
    )

    try:
        session = parse_roc_date(str(row.get(date_field, "")))
        volume = int(str(row.get(volume_field, "")).replace(",", ""))
    except ValueError:
        return None

    if min(open_, high, low, close) <= 0:
        return None

    return Ohlcv(
        ts=clock.session_close(session),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        change=parse_change(str(row.get(change_field, "")), close),
    )


async def fetch_reports(
    urls: Mapping[MarketType, str], timeout_seconds: float, logger: ILoggingProvider
) -> dict[MarketType, list[dict[str, Any]]]:
    """
    Each exchange's report at its URL, its rows as served but for the NUL characters in their text, which PostgreSQL's
    text refuses. A report that fails to load is logged and left out.
    """
    reports: dict[MarketType, list[dict[str, Any]]] = {}

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
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
                logger.error(f"Failed to fetch {url}: {error}")

    return reports


async def read_reports[Readings: Collection[Any]](
    urls: Mapping[MarketType, str],
    read: Callable[[list[dict[str, Any]], MarketType], Readings],
    timeout_seconds: float,
    logger: ILoggingProvider,
) -> dict[MarketType, Readings]:
    """
    Each exchange's report at its URL (fetch_reports), as `read` reads its rows. A report of which nothing was read
    is logged (log_unread).
    """
    read_by_market: dict[MarketType, Readings] = {}

    for market, rows in (await fetch_reports(urls, timeout_seconds, logger)).items():
        read_by_market[market] = read(rows, market)
        log_unread(urls[market], rows, len(read_by_market[market]), logger)

    return read_by_market


def log_unread(url: str, rows: list[dict[str, Any]], read: int, logger: ILoggingProvider) -> None:
    """
    Logs a report of which nothing was read. One that served rows none of which could be read, as when the exchange
    renames a field, is an error: what it serves now is lost to the archive, since the OpenAPI serves only its latest
    period. One that served no rows is logged as information: a row holding nothing but the day it was served is how
    the OpenAPI serves nothing, as for an industry format no company has filed yet. A report that failed to load is
    logged by fetch_reports.
    """
    if read:
        return

    served = served_rows(rows)

    if not served:
        logger.info(f"Open data feed {url} served no rows")
        return

    logger.error(f"Open data feed {url} served {len(served)} rows and none could be read")


def served_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows that hold more than the day they were served, which is all a row of an empty OpenAPI report holds."""
    return [row for row in rows if sum(1 for value in row.values() if str(value).strip()) > 1]


def parse_industries(rows: list[dict[str, Any]], market: MarketType, exchange: ExchangeSources) -> dict[str, str]:
    """One market's stock_id -> industry name. A company whose industry code has no name in the settings is absent."""
    feed, names = exchange.company_profiles[market], exchange.industry_names
    return {
        str(row[feed.stock_id]).strip(): names[code]
        for row in rows
        if row.get(feed.stock_id) and (code := str(row.get(feed.industry, "")).strip()) in names
    }


def parse_company_profile(
    row: dict[str, Any], market: MarketType, exchange: ExchangeSources, fetched_at: datetime
) -> CompanyProfile | None:
    """One company's profile as its row serves it, a blank field None; None when the row names no company."""
    feed = exchange.company_profiles[market]

    if not (stock_id := served_field(row, [feed.stock_id])):
        return None

    capital, shares = parse_number(served_field(row, [feed.paid_in_capital])), parse_number(served_field(row, [feed.issued_shares]))

    return CompanyProfile(
        stock_id=stock_id,
        market=market,
        full_name=served_field(row, [feed.full_name]) or None,
        short_name=served_field(row, [feed.short_name]) or None,
        english_short_name=served_field(row, [feed.english_short_name]) or None,
        industry_code=served_field(row, [feed.industry]) or None,
        founded_on=parse_optional_date(served_field(row, [feed.founded_on])),
        listed_on=parse_optional_date(served_field(row, [feed.listed_on])),
        paid_in_capital=capital if capital is not None and capital >= 0 else None,
        issued_shares=int(shares) if shares is not None and shares >= 0 else None,
        chairman=served_field(row, [feed.chairman]) or None,
        general_manager=served_field(row, [feed.general_manager]) or None,
        address=served_field(row, [feed.address]) or None,
        website=web_address(served_field(row, [feed.website]), exchange.website_scheme),
        reported_on=parse_optional_roc_date(served_field(row, [feed.report_date])),
        fetched_at=fetched_at,
    )


def parse_announcement(
    row: dict[str, Any], market: MarketType, fetched_at: datetime, exchange: ExchangeSources, clock: IMarketClock
) -> Article | None:
    """
    One material information announcement, its subject the title and its text the content, both as served, or None
    when the row names no company or no valid date and time.
    """
    feed = exchange.material_information[market]
    stock_id, time_text = str(row.get(feed.stock_id, "")).strip(), str(row.get(feed.time, "")).zfill(6)

    try:
        announced_at = clock.session_close(parse_roc_date(str(row.get(feed.date, "")))).replace(
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
        fact_date=parse_optional_roc_date(str(row.get(feed.fact_date, ""))),
    )


def parse_quarter_eps(
    rows: list[dict[str, Any]], market: MarketType, exchange: ExchangeSources, clock: IMarketClock
) -> dict[str, Eps]:
    """One market's year-to-date EPS by stock_id, leaving out a row without a number or a valid ROC year and quarter."""
    feed, fetched_at = exchange.quarter_eps[market], clock.now()
    filed: dict[str, Eps] = {}

    for row in rows:
        stock_id = str(row.get(feed.stock_id, "")).strip()

        try:
            quarter = FiscalQuarter(int(str(row.get(feed.year, ""))) + ROC_YEAR_OFFSET, int(str(row.get(feed.quarter, ""))))
        except ValueError:
            continue

        if stock_id and (value := parse_number(str(row.get(feed.eps, "")))) is not None:
            filed[stock_id] = Eps(
                value=value,
                kind=EpsKind.CUMULATIVE,
                period_end=quarter,
                basis=EpsBasis.ACTUAL,
                source=InformationSource.TWSE_MOPS,
                fetched_at=fetched_at,
            )

    return filed


def parse_valuation_ratios(rows: list[dict[str, Any]], market: MarketType, exchange: ExchangeSources) -> list[ValuationRatios]:
    """One market's valuation ratios, leaving out a row without a stock or a valid session date."""
    feed = exchange.valuation_ratios[market]
    published: list[ValuationRatios] = []

    for row in rows:
        stock_id = str(row.get(feed.stock_id, "")).strip()

        if not stock_id or (session := parse_optional_roc_date(str(row.get(feed.date, "")))) is None:
            continue

        published.append(
            ValuationRatios(
                stock_id=stock_id,
                session_date=session,
                pe_ratio=parse_number(str(row.get(feed.pe_ratio, ""))),
                dividend_yield=parse_number(str(row.get(feed.dividend_yield, ""))),
                pb_ratio=parse_number(str(row.get(feed.pb_ratio, ""))),
            )
        )

    return published


def parse_financial_report(
    row: dict[str, Any], market: MarketType, statement: FinancialStatement, industry_format: IndustryFormat, exchange: ExchangeSources
) -> FinancialReport | None:
    """
    One company's statement of one report, or None when the row names no company or no valid ROC year, quarter and
    served date: a report of a format nobody filed yet serves one row with only its date.
    """
    feeds = exchange.financial_reports
    stock_id = served_field(row, feeds.stock_id)

    try:
        year, quarter = (int(served_field(row, names)) for names in (feeds.year, feeds.quarter))
        period = FiscalQuarter(year + ROC_YEAR_OFFSET, quarter)
        served_date = parse_roc_date(served_field(row, feeds.served_date))
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


def served_field(row: dict[str, Any], names: list[str]) -> str:
    """The value of the first of the names the row holds, stripped, or '' when it holds none of them."""
    return next((str(row[name]).strip() for name in names if name in row), "")


def parse_exchange_news(row: dict[str, Any], exchange: ExchangeSources) -> ExchangeNews | None:
    """One news item, or None when it has no address or no valid ROC date."""
    feed = exchange.exchange_news
    url = served_field(row, [feed.link])

    if not url or (published_on := parse_optional_roc_date(served_field(row, [feed.date]))) is None:
        return None

    return ExchangeNews(url=url, title=served_field(row, [feed.title]), published_on=published_on)


def parse_twse_index(rows: list[dict[str, Any]], exchange: ExchangeSources, clock: IMarketClock) -> list[Ohlcv]:
    """The TAIEX in MI_INDEX, which lists every TWSE index of one session and writes the change's sign apart."""
    fields = exchange.twse_index_fields
    closes: list[Ohlcv] = []

    for row in rows:
        if row.get(fields.index) != fields.taiex:
            continue

        try:
            session = parse_roc_date(str(row.get(fields.date, "")))
        except ValueError:
            continue

        sign = "-" if row.get(fields.sign) == "-" else ""
        close_text, change_text = str(row.get(fields.close, "")), sign + str(row.get(fields.change, ""))

        if (close := parse_index_close(session, close_text, change_text, clock)) is not None:
            closes.append(close)

    return closes


def parse_tpex_index(rows: list[dict[str, Any]], clock: IMarketClock) -> list[Ohlcv]:
    """The TPEx Index in tpex_index, one row per recent session, dated '20261106'."""
    closes: list[Ohlcv] = []

    for row in rows:
        try:
            session = date.fromisoformat(str(row.get("Date", "")))
        except ValueError:
            continue

        if (close := parse_index_close(session, str(row.get("Close", "")), str(row.get("Change", "")), clock)) is not None:
            closes.append(close)

    return closes


def parse_index_close(session: date, close_text: str, change_text: str, clock: IMarketClock) -> Ohlcv | None:
    """The index's close of the session with its signed change, or None when the close is not a positive number."""
    close = parse_number(close_text)

    if close is None or close <= 0:
        return None

    return Ohlcv(ts=clock.session_close(session), close=close, change=parse_change(change_text, close))
