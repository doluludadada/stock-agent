from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Protocol

from a_domain.model.fundamentals.eps import Eps
from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.daily_close_archive import ExchangeNews, FinancialReport, ValuationRatios
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.types.enums import FinancialStatement, IndustryFormat, MarketType


class ITaiwanStockProvider(IStockProvider, Protocol):
    """
    The TWSE and TPEX OpenAPI: the daily-quotes listings with every listed and OTC stock and its latest official close,
    the daily index reports, the company profiles that give each company's industry, and the reports it serves only for
    their latest day, month or quarter: the material information, the EPS statistics, the valuation ratios, the balance
    sheets and income statements, the monthly revenue and TWSE's own news.
    """

    async def cached_stocks(self) -> list[Stock]:
        """The listed stocks, fetched again once the cached listings are older than the cache lifetime."""
        ...

    async def fetch_listings(self) -> tuple[list[Stock], dict[str, Ohlcv]]:
        """Both listings' stocks and their closes. A failed fetch is logged and yields neither."""
        ...

    def parse_listing(self, rows: list[dict[str, Any]], market: MarketType) -> tuple[list[Stock], dict[str, Ohlcv]]:
        """The stocks with a four-digit code in one exchange's listing, and the official close of each that traded."""
        ...

    def parse_roc_date(self, text: str) -> date:
        """'1151029' (ROC year 115) is 2026-10-29."""
        ...

    def parse_optional_roc_date(self, text: str) -> date | None:
        """The ROC date the text writes, or None when it writes none."""
        ...

    def parse_daily_close(self, row: dict[str, Any], fields: tuple[str, str, str, str, str, str, str]) -> Ohlcv | None:
        """
        The row's official daily bar with its change, or None when the stock did not trade (TWSE leaves prices blank,
        TPEX writes '---').
        """
        ...

    async def fetch_reports(self, urls: Mapping[MarketType, str]) -> dict[MarketType, list[dict[str, Any]]]:
        """
        Each exchange's report at its URL, its rows as served but for the NUL characters in their text, which PostgreSQL's
        text refuses. A report that fails to load is logged and left out.
        """
        ...

    async def fetch_industries(self) -> dict[str, str]:
        """
        stock_id -> industry name from both exchanges' company profiles, merged. A market's profiles are reused until
        they are industry_max_age_hours old; a market whose download fails keeps the ones it had.
        """
        ...

    def parse_industries(self, rows: list[dict[str, Any]], market: MarketType) -> dict[str, str]:
        """One market's stock_id -> industry name. A company whose industry code has no name in the settings is absent."""
        ...

    async def fetch_material_information(self) -> list[Article]:
        """Both exchanges' material information as served now: each announcement under the date and time its row names."""
        ...

    def parse_announcement(self, row: dict[str, Any], market: MarketType, fetched_at: datetime) -> Article | None:
        """
        One material information announcement, its subject the title and its text the content, both as served, or None
        when the row names no company or no valid date and time.
        """
        ...

    async def fetch_quarter_eps(self) -> dict[str, Eps]:
        """
        stock_id -> the year-to-date basic EPS of the quarter its row names, as served, from both exchanges' EPS
        statistics, which hold the companies that filed the latest quarter.
        """
        ...

    def parse_quarter_eps(self, rows: list[dict[str, Any]], market: MarketType) -> dict[str, Eps]:
        """One market's year-to-date EPS by stock_id, leaving out a row without a number or a valid ROC year and quarter."""
        ...

    async def fetch_valuation_ratios(self) -> list[ValuationRatios]:
        """Both exchanges' valuation ratios as served now, each under the session its row names."""
        ...

    def parse_valuation_ratios(self, rows: list[dict[str, Any]], market: MarketType) -> list[ValuationRatios]:
        """One market's valuation ratios, leaving out a row without a stock or a valid session date."""
        ...

    async def fetch_financial_reports(self) -> list[FinancialReport]:
        """
        Both exchanges' balance sheets and income statements of every industry format as served now, which hold the
        companies that filed the latest quarter, each under the quarter its row names.
        """
        ...

    def parse_financial_report(
        self, row: dict[str, Any], market: MarketType, statement: FinancialStatement, industry_format: IndustryFormat
    ) -> FinancialReport | None:
        """
        One company's statement of one report, or None when the row names no company or no valid ROC year, quarter and
        served date: a report of a format nobody filed yet serves one row with only its date.
        """
        ...

    def served_field(self, row: dict[str, Any], names: list[str]) -> str:
        """The value of the first of the names the row holds, stripped, or '' when it holds none of them."""
        ...

    async def fetch_monthly_revenues(self) -> list[MonthlyRevenue]:
        """Both exchanges' monthly revenue summaries as served now, each row under the month it names."""
        ...

    def parse_monthly_revenue(self, row: dict[str, Any], market: MarketType) -> MonthlyRevenue | None:
        """
        One company's revenue of the month its row names ('11509' is 2026-09), or None when the row names no company or
        no valid month or served date.
        """
        ...

    async def fetch_exchange_news(self) -> list[ExchangeNews]:
        """TWSE's own news list as served now, each item under the day it is dated."""
        ...

    def parse_exchange_news(self, row: dict[str, Any]) -> ExchangeNews | None:
        """One news item, or None when it has no address or no valid ROC date."""
        ...

    def parse_number(self, text: str) -> float | None:
        """A number as written ('25.96', '-1.05', '1,234.5'), or None when the report leaves it blank or writes no finite one."""
        ...

    async def fetch_index_closes(self) -> dict[MarketType, list[Ohlcv]]:
        """
        Each exchange's own index in its daily index report, TWSE's TAIEX and TPEX's TPEx Index: a bar per session the
        report serves, stamped at the session's close, with only the close and the change. An exchange whose report
        fails to load is logged and left out.
        """
        ...

    def parse_twse_index(self, rows: list[dict[str, Any]]) -> list[Ohlcv]:
        """The TAIEX in MI_INDEX, which lists every TWSE index of one session and writes the change's sign apart."""
        ...

    def parse_tpex_index(self, rows: list[dict[str, Any]]) -> list[Ohlcv]:
        """The TPEx Index in tpex_index, one row per recent session, dated '20261106'."""
        ...

    def parse_index_close(self, session: date, close_text: str, change_text: str) -> Ohlcv | None:
        """The index's close of the session with its signed change, or None when the close is not a positive number."""
        ...

    def parse_change(self, text: str, close: float) -> float | None:
        """
        The listing's signed change from the reference price ('-10.0000', '+1.00 '), or None when it is not a number or
        leaves no positive reference price under this close.
        """
        ...
