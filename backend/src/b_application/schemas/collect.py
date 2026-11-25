from dataclasses import dataclass
from datetime import date, time

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.world_indicator import IndicatorReading
from a_domain.ports.market.daily_close_archive import ArchivedMonth, ArchivedQuarter, ArchivedSession
from a_domain.rules.market.quote_refresh import QuoteRefresh
from a_domain.types.enums import MarketIndex, MarketType


@dataclass(frozen=True)
class StockFinancials:
    """A stock page's financials, as Pipeline.load_financials returns them: what the open-data archive holds of the stock."""

    quarters: list[QuarterFinancials]
    """Each quarter's figures as the open-data archive holds them, oldest first."""

    monthly_revenues: list[MonthlyRevenue]
    """Each month's revenue as the open-data archive holds it, oldest first."""


@dataclass(frozen=True)
class RealtimeQuotes:
    """The pages' realtime quotes, as PageQuotes answers them for Pipeline.load_page_quotes."""

    quotes: dict[str, Ohlcv]
    """Today's quote of each stock asked for that traded today, by stock id."""

    indexes: dict[MarketIndex, Ohlcv]
    """Today's quote of each market index asked for that has a value of today."""

    refresh: QuoteRefresh
    """Whether the quotes may still change, and when a page asks again."""


@dataclass(frozen=True)
class ArchivedPeriods:
    """What the open-data archive holds after a save, as DailyCloseArchiver answers it for Pipeline.archive_daily_closes."""

    sessions: list[ArchivedSession]
    """Every date the archive holds closes of."""

    quarters: list[ArchivedQuarter]
    """Every quarter the archive holds figures of."""

    months: list[ArchivedMonth]
    """Every month the archive holds revenue of."""


@dataclass(frozen=True)
class HistoryCoverage:
    """How whole the exchanges' history cache is over a window, as DailyHistoryBackfill answers it."""

    held: list[date]
    """The sessions the cache holds reported bars of."""

    lacking: list[date]
    """The index sessions it still lacks reported bars of."""

    unread: list[tuple[MarketType, date, date]]
    """Each exchange's ranges of its index or its ex-right references it could not read: the history is not whole."""


@dataclass(frozen=True)
class HistoryBackfill:
    """What `just backfill-history` brought back, as Pipeline.backfill_history returns it. A part the site does not read is None."""

    history: HistoryCoverage | None
    """DailyHistoryBackfill: the daily history's sessions held and lacking and the ranges it could not read."""

    revenue: tuple[int, int] | None
    """FundamentalsHistoryBackfill: the months of revenue read, and the months that were due."""

    eps: tuple[int, int] | None
    """FundamentalsHistoryBackfill: the quarters of EPS held, and the quarters that were due."""


@dataclass(frozen=True)
class ArticleBackfill:
    """What `just backfill-articles` did, as Pipeline.backfill_article_store returns it."""

    kept: int
    """The announcements and TWSE news items it added to the article store or replaced there."""

    stocks: int
    """The stocks the article store keeps articles of."""

    embedded: int
    """The articles it embedded."""


@dataclass(frozen=True)
class CompanyBackfill:
    """What `just backfill-company-background` read, as Pipeline.backfill_company_background returns it."""

    companies: int
    """The companies of the monthly ranking it was asked for."""

    businesses: tuple[int, int]
    """MainBusinessRefresh: the main businesses read, and those left due."""

    reports: tuple[int, int]
    """AnnualReportRefresh: the annual reports read, and the companies left due."""


@dataclass(frozen=True)
class WorldOverview:
    """What the site holds of the world, as WorldLookup answers it for Pipeline.load_world."""

    readings: list[IndicatorReading]
    """Each held world indicator's newest reading beside the one before it."""

    briefs: list[StockBrief]
    """The written world briefs of the latest days, newest first."""

    news: list[Article]
    """The newest kept world news items."""

    write_at: time | None
    """The Taipei time from which the site writes the day's brief, None while it writes none."""
