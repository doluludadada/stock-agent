import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import ClassVar, Self

from sqlalchemy import JSON, BigInteger, Column
from sqlmodel import Field, SQLModel

from a_domain.model.fundamentals.eps import Eps
from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.daily_close_archive import ExchangeNews, FinancialReport, ValuationRatios
from a_domain.types.enums import ContentType, IndustryFormat, InformationSource, MarketType
from a_domain.types.values import FiscalQuarter
from b_application.config.sources_config import FinancialSummaryFields
from c_infrastructure.database.utc_datetime import UtcDateTime


class DailyCloseDTO(SQLModel, table=True):
    """
    One stock's official daily bar of one session from the TWSE or TPEX OpenAPI listing, the archive's (IDailyCloseArchive).
    No bar of the cached history in ohlcv_data is ever written here.
    """

    __tablename__: ClassVar[str] = "daily_close_archive"

    stock_id: str = Field(primary_key=True)
    session_date: date = Field(primary_key=True, index=True)
    """Indexed on its own: the primary key leads with stock_id, and the archive's warm-up counts the distinct sessions."""

    market: str
    open: float
    high: float
    low: float
    close: float
    volume: int = Field(sa_type=BigInteger)
    """Shares traded. An ETF has traded over a billion in a session, near PostgreSQL's INTEGER limit."""
    change: float | None = None

    @classmethod
    def from_domain(cls, stock: Stock, bar: Ohlcv, session_date: date) -> Self:
        return cls(
            stock_id=stock.stock_id,
            session_date=session_date,
            market=stock.market.value,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            change=bar.change,
        )

    def to_domain(self, ts: datetime) -> Ohlcv:
        """The bar, stamped `ts`: its session's close."""
        return Ohlcv(ts=ts, open=self.open, high=self.high, low=self.low, close=self.close, volume=self.volume, change=self.change)


class IndexCloseDTO(SQLModel, table=True):
    """One exchange's own index close of one session: the TAIEX under twse, the TPEx Index under tpex."""

    __tablename__: ClassVar[str] = "index_close_archive"

    market: str = Field(primary_key=True)
    session_date: date = Field(primary_key=True)
    close: float
    change: float | None = None

    @classmethod
    def from_domain(cls, market: MarketType, bar: Ohlcv, session_date: date) -> Self:
        return cls(market=market.value, session_date=session_date, close=bar.close, change=bar.change)

    def to_domain(self, ts: datetime) -> Ohlcv:
        """The close as a bar stamped `ts`, its session's close. The report gives no open, high, low or volume."""
        return Ohlcv(ts=ts, open=self.close, high=self.close, low=self.close, close=self.close, change=self.change)


class MaterialInformationDTO(SQLModel, table=True):
    """
    One company's material information announcement from the TWSE or TPEX OpenAPI, under the time it was announced:
    its subject, the clause it is filed under and its text as served, and the day of the fact it reports.
    """

    __tablename__: ClassVar[str] = "material_information_archive"

    stock_id: str = Field(primary_key=True)
    announced_at: datetime = Field(primary_key=True, sa_type=UtcDateTime)
    subject: str
    clause: str
    fact_date: date | None = None
    description: str

    @classmethod
    def from_domain(cls, announcement: Article) -> Self:
        return cls(
            stock_id=announcement.stock_id,
            announced_at=announcement.published_at,
            subject=announcement.title,
            clause=announcement.clause or "",
            fact_date=announcement.fact_date,
            description=announcement.content,
        )

    def to_domain(self, fetched_at: datetime) -> Article:
        """The announcement as an article, read at `fetched_at`."""
        return Article(
            stock_id=self.stock_id,
            source=InformationSource.TWSE_MOPS,
            content_type=ContentType.FACT,
            title=self.subject,
            content=self.description,
            published_at=self.announced_at,
            fetched_at=fetched_at,
            clause=self.clause,
            fact_date=self.fact_date,
        )


class YearToDateEpsDTO(SQLModel, table=True):
    """One company's basic EPS of the year to a quarter's end, as the TWSE or TPEX OpenAPI's EPS statistics serve it."""

    __tablename__: ClassVar[str] = "quarter_eps_archive"

    stock_id: str = Field(primary_key=True)
    year: int = Field(primary_key=True)
    """The Gregorian year; the statistics write the ROC year."""

    quarter: int = Field(primary_key=True)
    eps: float

    @classmethod
    def from_domain(cls, stock_id: str, eps: Eps) -> Self:
        return cls(stock_id=stock_id, year=eps.period_end.year, quarter=eps.period_end.quarter, eps=eps.value)


class ValuationRatiosDTO(SQLModel, table=True):
    """One stock's P/E, dividend yield and P/B of one session, as its exchange's daily report gives them."""

    __tablename__: ClassVar[str] = "valuation_ratio_archive"

    stock_id: str = Field(primary_key=True)
    session_date: date = Field(primary_key=True)
    pe_ratio: float | None = None
    dividend_yield: float | None = None
    pb_ratio: float | None = None

    @classmethod
    def from_domain(cls, ratios: ValuationRatios) -> Self:
        return cls(
            stock_id=ratios.stock_id,
            session_date=ratios.session_date,
            pe_ratio=ratios.pe_ratio,
            dividend_yield=ratios.dividend_yield,
            pb_ratio=ratios.pb_ratio,
        )


class FinancialReportDTO(SQLModel, table=True):
    """
    One company's balance sheet or income statement of one quarter as the TWSE or TPEX OpenAPI served it: its market,
    industry format and served date, and every other field of the row with its value as served.
    """

    __tablename__: ClassVar[str] = "financial_report_archive"

    stock_id: str = Field(primary_key=True)
    year: int = Field(primary_key=True)
    """The Gregorian year; the reports write the ROC year."""

    quarter: int = Field(primary_key=True)
    statement: str = Field(primary_key=True)
    market: str
    industry_format: str
    served_date: date
    items: dict[str, str] = Field(sa_column=Column(JSON, nullable=False))

    @classmethod
    def from_domain(cls, report: FinancialReport) -> Self:
        return cls(
            stock_id=report.stock_id,
            year=report.quarter.year,
            quarter=report.quarter.quarter,
            statement=report.statement.value,
            market=report.market.value,
            industry_format=report.industry_format.value,
            served_date=report.served_date,
            items=report.items,
        )

    @classmethod
    def summarize(
        cls,
        quarter: FiscalQuarter,
        reports: Sequence[Self],
        eps: float | None,
        summary: Mapping[IndustryFormat, FinancialSummaryFields],
    ) -> QuarterFinancials:
        """
        The quarter's figures from its statements, read by the columns `summary` names for their industry format, and its
        year-to-date EPS; only the EPS when the archive holds no statement of the quarter. The two statements share no
        column a figure reads, so their items are read as one.
        """
        if not reports:
            return QuarterFinancials(quarter=quarter, eps=eps)

        items = {name: value for report in reports for name, value in report.items.items()}
        columns = summary[IndustryFormat(reports[0].industry_format)]
        return QuarterFinancials(
            quarter=quarter,
            revenue=cls.figure(items, columns.revenue),
            gross_profit=cls.figure(items, columns.gross_profit),
            operating_income=cls.figure(items, columns.operating_income),
            net_income=cls.figure(items, columns.net_income),
            eps=eps,
            total_assets=cls.figure(items, columns.total_assets),
            total_liabilities=cls.figure(items, columns.total_liabilities),
            equity=cls.figure(items, columns.equity),
            book_value_per_share=cls.figure(items, columns.book_value_per_share),
        )

    @staticmethod
    def figure(items: Mapping[str, str], columns: list[str]) -> float | None:
        """The first of the columns the items fill, as a number, or None when they fill none of them or no finite number."""
        text = next((items[column] for column in columns if items.get(column, "").strip()), "")

        try:
            value = float(text.replace(",", ""))
        except ValueError:
            return None

        return value if math.isfinite(value) else None


class MonthlyRevenueDTO(SQLModel, table=True):
    """One company's revenue of one month, as the TWSE or TPEX OpenAPI's monthly revenue summary served it."""

    __tablename__: ClassVar[str] = "monthly_revenue_archive"

    stock_id: str = Field(primary_key=True)
    year: int = Field(primary_key=True)
    """The Gregorian year; the summaries write the ROC year."""

    month: int = Field(primary_key=True)
    market: str
    served_date: date
    company_name: str
    industry: str
    revenue: float | None = None
    previous_month_revenue: float | None = None
    last_year_revenue: float | None = None
    month_over_month_percent: float | None = None
    year_over_year_percent: float | None = None
    cumulative_revenue: float | None = None
    last_year_cumulative_revenue: float | None = None
    cumulative_year_over_year_percent: float | None = None
    note: str

    @classmethod
    def from_domain(cls, revenue: MonthlyRevenue) -> Self:
        return cls.model_validate(revenue, from_attributes=True)

    def to_domain(self) -> MonthlyRevenue:
        return MonthlyRevenue(**self.model_dump())


class ExchangeNewsDTO(SQLModel, table=True):
    """One item of TWSE's own news list, under its address."""

    __tablename__: ClassVar[str] = "exchange_news_archive"

    url: str = Field(primary_key=True)
    title: str
    published_on: date

    @classmethod
    def from_domain(cls, news: ExchangeNews) -> Self:
        return cls(url=news.url, title=news.title, published_on=news.published_on)

    def to_domain(self, stock_id: str, published_at: datetime, fetched_at: datetime) -> Article:
        """The item as an article about the stock its title names, published at `published_at` and read at `fetched_at`."""
        return Article(
            stock_id=stock_id,
            source=InformationSource.TWSE_NEWS,
            content_type=ContentType.NEWS,
            title=self.title,
            content=self.title,
            url=self.url,
            published_at=published_at,
            fetched_at=fetched_at,
        )
