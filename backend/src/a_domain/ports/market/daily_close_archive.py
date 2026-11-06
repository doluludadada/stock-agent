from datetime import date
from typing import Annotated, Protocol

from pydantic import Field, FiniteFloat
from pydantic.dataclasses import dataclass

from a_domain.model.fundamentals.eps import Eps
from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.types.enums import FinancialStatement, IndustryFormat, MarketType
from a_domain.types.values import FiscalQuarter


@dataclass(frozen=True)
class ValuationRatios:
    """
    One stock's P/E, dividend yield (percent) and P/B on one session, as its exchange's daily report gives them. A ratio
    the report leaves blank, such as the P/E of a company with losses, is None.
    """

    stock_id: str
    session_date: date
    pe_ratio: FiniteFloat | None
    dividend_yield: FiniteFloat | None
    pb_ratio: FiniteFloat | None


@dataclass(frozen=True)
class FinancialReport:
    """
    One company's balance sheet or income statement of one quarter, as its exchange's OpenAPI serves it in the report of
    the company's industry format, and the day the exchange served it. Its items are every field of the row but the
    company's code and name, the period and that day, by the name the report gives the field, with the value as served,
    so that what is read from them can be read again differently: the source serves only the latest quarter.
    """

    stock_id: str
    quarter: FiscalQuarter
    statement: FinancialStatement
    market: MarketType
    industry_format: IndustryFormat
    served_date: date
    items: dict[str, str]


@dataclass(frozen=True)
class ExchangeNews:
    """One item of TWSE's own news list: its title and address, and the day it is dated."""

    url: str
    title: str
    published_on: date


@dataclass(frozen=True)
class OpenDataDownload:
    """
    What one run of the archive downloaded from the TWSE and TPEX OpenAPI: each listed stock with its latest official
    daily bar, each exchange's own index closes, the material information, each company's year-to-date EPS of the
    latest quarter, the valuation ratios, the balance sheets and income statements, the monthly revenue and TWSE's own
    news, each as served.
    """

    stocks: list[Stock]
    indexes: dict[MarketType, list[Ohlcv]]
    material_information: list[Article]
    quarter_eps: dict[str, Eps]
    valuation_ratios: list[ValuationRatios]
    financial_reports: list[FinancialReport]
    monthly_revenues: list[MonthlyRevenue]
    exchange_news: list[ExchangeNews]

    @property
    def is_empty(self) -> bool:
        """Every listing and report failed to load or served nothing."""
        reports = (self.material_information, self.quarter_eps, self.valuation_ratios, self.financial_reports, self.monthly_revenues)
        return not (self.stocks or any(self.indexes.values()) or any(reports) or self.exchange_news)


@dataclass(frozen=True)
class ArchivedSession:
    """
    One date the archive holds something of, and how much: the closes of stocks and of the exchanges' own indexes and
    the stocks' valuation ratios of that session, and the material information and the TWSE news of that day.
    """

    session_date: date
    stocks: Annotated[int, Field(ge=0)]
    indexes: Annotated[int, Field(ge=0)]
    valuation_ratios: Annotated[int, Field(ge=0)]
    material_information: Annotated[int, Field(ge=0)]
    exchange_news: Annotated[int, Field(ge=0)]


@dataclass(frozen=True)
class ArchivedQuarter:
    """One quarter the archive holds something of, and of how many companies: year-to-date EPS and each statement."""

    quarter: FiscalQuarter
    eps: Annotated[int, Field(ge=0)]
    balance_sheets: Annotated[int, Field(ge=0)]
    income_statements: Annotated[int, Field(ge=0)]


@dataclass(frozen=True)
class ArchivedMonth:
    """One month the archive holds revenue of, and of how many companies."""

    year: int
    month: Annotated[int, Field(ge=1, le=12)]
    companies: Annotated[int, Field(ge=0)]


class IDailyCloseArchive(IOhlcvProvider, INewsProvider, Protocol):
    """
    What the TWSE and TPEX OpenAPI publish under the Open Government Data License v1 but serve only for their latest
    session, day, month or quarter, so that a public site may show what it computes from them: every session's official
    closes, the material information each company announced, the companies' year-to-date EPS, balance sheets and income
    statements of each quarter, their revenue of each month, each session's valuation ratios and TWSE's own news. What
    the archive did not save in time is lost. It is kept apart from the cached daily history, whose source forbids
    redistribution, so the two never mix.

    It is the only price source of an open-data deployment (Audience.open_data_only): fetch_history serves the stocks'
    archived closes and fetch_index_history an index's, each bar stamped at its session's close. An index's report
    gives its close only, so its bar's open, high and low are that close and its volume 0. The archive holds no
    realtime quote: fetch_realtime_bars raises RealtimeQuotesUnavailable.

    It is also the only news source of an audience without news articles (Audience.news_articles): fetch_news serves a
    stock's archived material information and the TWSE news whose title names its code, of the last
    analysis.material_information_days, newest first. The AI step of every audience reads a stock's financials.
    """

    async def save(self, download: OpenDataDownload) -> None:
        """
        Saves each stock's daily bars under its market, each exchange's own index closes (TWSE's TAIEX, TPEX's TPEx
        Index) under the session of each bar, each announcement under its company and the time it was announced, each
        company's year-to-date EPS under its quarter, each stock's valuation ratios under their session, each financial
        report under its company, quarter and statement, each monthly revenue under its company and month, and each
        TWSE news item under its address. What the archive holds under the same key is replaced, so saving the same
        data again changes nothing.
        """
        ...

    async def sessions(self) -> list[ArchivedSession]:
        """Every date the archive holds something of, oldest first."""
        ...

    async def quarters(self) -> list[ArchivedQuarter]:
        """Every quarter the archive holds EPS or a financial report of, oldest first."""
        ...

    async def months(self) -> list[ArchivedMonth]:
        """Every month the archive holds revenue of, oldest first."""
        ...

    async def financials(self, stock_id: str) -> tuple[list[QuarterFinancials], list[MonthlyRevenue]]:
        """
        The stock's figures of every quarter the archive holds its EPS or a financial report of, read from its reports
        by the columns sources.exchange.financial_reports.summary names for their industry format, and its revenue of
        every month the archive holds; both oldest first.
        """
        ...

    async def session_count(self) -> int:
        """How many sessions hold stock closes: the most daily bars the archive can serve one stock."""
        ...
