from typing import Protocol

from a_domain.model.fundamentals.eps import Eps
from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.market.article import Article
from a_domain.model.market.company_profile import CompanyProfile
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.daily_close_archive import ExchangeNews, FinancialReport, ValuationRatios
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.types.enums import MarketType


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

    async def fetch_industries(self) -> dict[str, str]:
        """
        stock_id -> industry name from both exchanges' company profiles, merged. A market's profiles are reused until
        they are industry_max_age_hours old; a market whose download fails keeps the ones it had.
        """
        ...

    async def fetch_company_profiles(self) -> list[CompanyProfile]:
        """
        Both exchanges' company profiles as served now, one per company: its names, industry code, dates, capital,
        people, address and website, the website as an http or https address. A market whose download fails is left out.
        """
        ...

    async def fetch_material_information(self) -> list[Article]:
        """Both exchanges' material information as served now: each announcement under the date and time its row names."""
        ...

    async def fetch_quarter_eps(self) -> dict[str, Eps]:
        """
        stock_id -> the year-to-date basic EPS of the quarter its row names, as served, from both exchanges' EPS
        statistics, which hold the companies that filed the latest quarter.
        """
        ...

    async def fetch_valuation_ratios(self) -> list[ValuationRatios]:
        """Both exchanges' valuation ratios as served now, each under the session its row names."""
        ...

    async def fetch_financial_reports(self) -> list[FinancialReport]:
        """
        Both exchanges' balance sheets and income statements of every industry format as served now, which hold the
        companies that filed the latest quarter, each under the quarter its row names.
        """
        ...

    async def fetch_monthly_revenues(self) -> list[MonthlyRevenue]:
        """Both exchanges' monthly revenue summaries as served now, each row under the month it names."""
        ...

    async def fetch_exchange_news(self) -> list[ExchangeNews]:
        """TWSE's own news list as served now, each item under the day it is dated."""
        ...

    async def fetch_index_closes(self) -> dict[MarketType, list[Ohlcv]]:
        """
        Each exchange's own index in its daily index report, TWSE's TAIEX and TPEX's TPEx Index: a bar per session the
        report serves, stamped at the session's close, with only the close and the change. An exchange whose report
        fails to load is logged and left out.
        """
        ...
