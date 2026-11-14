"""Fakes for the Protocols in a_domain/ports.

Each fake answers like its real adapter and records what the outside system
behind that port would observe: rows written, prompts sent, orders placed.
"""

import inspect
import itertools
import json
import math
import re
import zlib
from collections.abc import Collection, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from pydantic import SecretStr

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.model.chat.conversation import Conversation
from a_domain.model.chat.message import Message
from a_domain.model.fundamentals.eps import Eps
from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.system.user import User, UserSession
from a_domain.model.trading.account import (
    Account,
    AccountOpening,
    AccountSnapshot,
    BrokerageStatement,
    BrokerFill,
    Position,
    Settlement,
)
from a_domain.model.trading.backtest import Backtest
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.ports.market.daily_close_archive import (
    ArchivedMonth,
    ArchivedQuarter,
    ArchivedSession,
    ExchangeNews,
    FinancialReport,
    OpenDataDownload,
    ValuationRatios,
)
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import SendRefusal
from a_domain.rules.fundamentals.trailing_eps import EpsFilings, QuarterEps
from a_domain.rules.technical.strategy import TechnicalSettings
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.order_rule import BrokerLink
from a_domain.rules.trading.ranking import ListedHistory, ListedHistoryRule
from a_domain.types.enums import (
    AiAnalysisFocus,
    AiProvider,
    BriefStatus,
    ExecutionProvider,
    FeatureVisibility,
    FinancialStatement,
    MarketIndex,
    MarketType,
    MessageRole,
    Role,
    SentimentLabel,
    TradeAction,
    UserStatus,
    WatchlistType,
    Workflow,
)
from a_domain.types.errors import (
    AlreadySetUpError,
    LastAdministratorError,
    SignInRequired,
    TechnicalSettingsConflictError,
    UserExistsError,
)
from a_domain.types.ids import BacktestId, DecisionId, RunId, SessionToken, UserId
from a_domain.types.values import FiscalQuarter, comparable_name
from b_application.config.api_config import FeaturesConfig
from b_application.config.market_data_config import MarketHoursConfig
from c_infrastructure.database.models.trading_journal_dto import RunStockReportDTO
from c_infrastructure.system.market_clock import TaiwanMarketClock

PROMPT_TEMPLATES = {
    AiAnalysisFocus.FUNDAMENTAL: "fundamental analysis of {stock_id}\n{articles_text}",
    AiAnalysisFocus.MOMENTUM: "momentum analysis of {stock_id}\n{articles_text}",
}
VALUATION_PROMPT_TEMPLATE = (
    "valuation explanation of {stock_id}\n{valuation_facts}\n{data_warnings}\n{valuation_rules}\n{articles_text}"
)
PROMPT_HEADER = re.compile(r"^(fundamental analysis|momentum analysis|valuation explanation) of (\S+)")


class RecordingLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []
        self.level: str | int = "INFO"

    def set_level(self, level: str | int) -> None:
        self.level = level

    def info(self, message: str) -> None:
        self.records.append(("info", message))

    def warning(self, message: str) -> None:
        self.records.append(("warning", message))

    def debug(self, message: str) -> None:
        self.records.append(("debug", message))

    def critical(self, message: str) -> None:
        self.records.append(("critical", message))

    def error(self, message: str) -> None:
        self.records.append(("error", message))

    def success(self, message: str) -> None:
        self.records.append(("success", message))

    def trace(self, message: str) -> None:
        self.records.append(("trace", message))

    def exception(self, message: str) -> None:
        self.records.append(("exception", message))


class FakeMarketClock(TaiwanMarketClock):
    """Taiwan-time clock whose current time is set by the test; the trading phase follows that time."""

    def __init__(self, now: datetime) -> None:
        super().__init__(MarketHoursConfig())
        self.current_time = now

    def now(self) -> datetime:
        return self.current_time


class FakeStockProvider:
    """
    Like TaiwanStockProvider, every call returns new copies of the listed stocks, as IStockProvider promises, and the
    OpenAPI's other reports as they are served now.
    """

    def __init__(self) -> None:
        self.stocks: dict[str, Stock] = {}
        self.closes: dict[str, Ohlcv] = {}
        self.index_closes: dict[MarketType, list[Ohlcv]] = {}
        self.industries: dict[str, str] = {}
        self.material_information: list[Article] = []
        self.quarter_eps: dict[str, Eps] = {}
        self.valuation_ratios: list[ValuationRatios] = []
        self.financial_reports: list[FinancialReport] = []
        self.monthly_revenues: list[MonthlyRevenue] = []
        self.exchange_news: list[ExchangeNews] = []

    async def get_all(self) -> list[Stock]:
        return [deepcopy(stock) for stock in self.stocks.values()]

    async def get_by_id(self, stock_id: str) -> Stock | None:
        stock = self.stocks.get(stock_id)
        return deepcopy(stock) if stock is not None else None

    async def get_latest_closes(self) -> dict[str, Ohlcv]:
        return dict(self.closes)

    async def fetch_index_closes(self) -> dict[MarketType, list[Ohlcv]]:
        return {market: list(bars) for market, bars in self.index_closes.items()}

    async def fetch_industries(self) -> dict[str, str]:
        return dict(self.industries)

    async def fetch_material_information(self) -> list[Article]:
        return [replace(article) for article in self.material_information]

    async def fetch_quarter_eps(self) -> dict[str, Eps]:
        return dict(self.quarter_eps)

    async def fetch_valuation_ratios(self) -> list[ValuationRatios]:
        return list(self.valuation_ratios)

    async def fetch_financial_reports(self) -> list[FinancialReport]:
        return list(self.financial_reports)

    async def fetch_monthly_revenues(self) -> list[MonthlyRevenue]:
        return list(self.monthly_revenues)

    async def fetch_exchange_news(self) -> list[ExchangeNews]:
        return list(self.exchange_news)


class FakeDailyCloseArchive:
    """
    IDailyCloseArchive in memory: each stock's and each exchange index's close per session, each announcement, each
    company's EPS per quarter, each stock's valuation ratios per session, each financial report, monthly revenue and
    TWSE news item, and every save it got. As news it serves a stock's announcements newest first; the window of days
    is the SQL archive's. As a stock's financials it serves what a test put in `held_financials`, which no save fills: the
    SQL archive's tests read them from real reports. A stock in `financials_failures` raises its error instead.
    """

    def __init__(self) -> None:
        self.stock_closes: dict[tuple[str, date], Ohlcv] = {}
        self.index_closes: dict[tuple[MarketType, date], Ohlcv] = {}
        self.announcements: dict[tuple[str, datetime], Article] = {}
        self.quarter_eps: dict[tuple[str, FiscalQuarter], float] = {}
        self.valuation_ratios: dict[tuple[str, date], ValuationRatios] = {}
        self.financial_reports: dict[tuple[str, FiscalQuarter, FinancialStatement], FinancialReport] = {}
        self.monthly_revenues: dict[tuple[str, int, int], MonthlyRevenue] = {}
        self.exchange_news: dict[str, ExchangeNews] = {}
        self.held_financials: dict[str, tuple[list[QuarterFinancials], list[MonthlyRevenue]]] = {}
        self.financials_failures: dict[str, Exception] = {}
        self.saves = 0

    async def save(self, download: OpenDataDownload) -> None:
        self.saves += 1
        self.stock_closes.update({(stock.stock_id, bar.ts.date()): bar for stock in download.stocks for bar in stock.ohlcv})
        self.index_closes.update({(market, bar.ts.date()): bar for market, bars in download.indexes.items() for bar in bars})
        self.announcements.update({(article.stock_id, article.published_at): article for article in download.material_information})
        self.quarter_eps.update({(stock_id, eps.period_end): eps.value for stock_id, eps in download.quarter_eps.items()})
        self.valuation_ratios.update({(ratios.stock_id, ratios.session_date): ratios for ratios in download.valuation_ratios})
        self.financial_reports.update(
            {(report.stock_id, report.quarter, report.statement): report for report in download.financial_reports}
        )
        self.monthly_revenues.update(
            {(revenue.stock_id, revenue.year, revenue.month): revenue for revenue in download.monthly_revenues}
        )
        self.exchange_news.update({news.url: news for news in download.exchange_news})

    async def valuation_history(self, stock_id: str) -> list[ValuationRatios]:
        held = [ratios for (held_id, _), ratios in self.valuation_ratios.items() if held_id == stock_id]
        return sorted(held, key=lambda ratios: ratios.session_date)

    async def sessions(self) -> list[ArchivedSession]:
        stocks = [day for _, day in self.stock_closes]
        indexes = [day for _, day in self.index_closes]
        ratios = [day for _, day in self.valuation_ratios]
        announced = [moment.date() for _, moment in self.announcements]
        news = [item.published_on for item in self.exchange_news.values()]
        return [
            ArchivedSession(
                session_date=day,
                stocks=stocks.count(day),
                indexes=indexes.count(day),
                valuation_ratios=ratios.count(day),
                material_information=announced.count(day),
                exchange_news=news.count(day),
            )
            for day in sorted({*stocks, *indexes, *ratios, *announced, *news})
        ]

    async def quarters(self) -> list[ArchivedQuarter]:
        eps = [quarter for _, quarter in self.quarter_eps]
        filed = [(quarter, statement) for _, quarter, statement in self.financial_reports]
        return [
            ArchivedQuarter(
                quarter=quarter,
                eps=eps.count(quarter),
                balance_sheets=filed.count((quarter, FinancialStatement.BALANCE_SHEET)),
                income_statements=filed.count((quarter, FinancialStatement.INCOME_STATEMENT)),
            )
            for quarter in sorted({*eps, *(quarter for quarter, _ in filed)})
        ]

    async def months(self) -> list[ArchivedMonth]:
        months = [(year, month) for _, year, month in self.monthly_revenues]
        return [ArchivedMonth(year=year, month=month, companies=months.count((year, month))) for year, month in sorted(set(months))]

    async def revenue_served(self) -> dict[tuple[MarketType, int, int], date]:
        served: dict[tuple[MarketType, int, int], date] = {}

        for revenue in self.monthly_revenues.values():
            key = (revenue.market, revenue.year, revenue.month)
            served[key] = max(served.get(key, revenue.served_date), revenue.served_date)

        return served

    async def revenue_history(self, first: date, last: date) -> dict[tuple[str, int, int], float | None]:
        return {
            key: revenue.revenue
            for key, revenue in self.monthly_revenues.items()
            if (first.year, first.month) <= (revenue.year, revenue.month) <= (last.year, last.month)
        }

    async def revenue_fingerprint(self) -> tuple[object, ...]:
        return tuple(self.monthly_revenues.values())

    async def financials(self, stock_id: str) -> tuple[list[QuarterFinancials], list[MonthlyRevenue]]:
        if stock_id in self.financials_failures:
            raise self.financials_failures[stock_id]

        quarters, revenues = self.held_financials.get(stock_id, ([], []))
        return list(quarters), list(revenues)

    async def session_count(self) -> int:
        return len({day for _, day in self.stock_closes})

    async def fetch_news(self, stock_id: str, limit: int = 10) -> list[Article]:
        held = sorted(
            (article for (held_id, _), article in self.announcements.items() if held_id == stock_id),
            key=lambda article: article.published_at,
        )
        return [replace(article) for article in reversed(held)][:limit]

    async def archived_articles(self, since: datetime) -> list[Article]:
        return [replace(article) for article in self.announcements.values() if article.published_at >= since]

    def save_as_md_file(self, stock_id: str, articles: list[Article]) -> None:
        return None


class FakeFundamentalsProvider:
    """
    MOPS stand-in: cumulative EPS filed per quarter, quarters that fail to fetch, and quarters whose refresh failed; and
    each market's monthly revenue summary per month, where a month it does not hold fails.
    """

    def __init__(self) -> None:
        self.monthly_revenue_summaries: dict[tuple[MarketType, int, int], list[MonthlyRevenue]] = {}
        self.cumulative_eps: dict[FiscalQuarter, dict[str, float]] = {}
        self.failed_quarters: set[FiscalQuarter] = set()
        self.refresh_failed_quarters: set[FiscalQuarter] = set()
        self.requested: list[set[FiscalQuarter]] = []
        self.fetched_at = datetime(2026, 10, 19, 18, 0)
        self.held_pages: dict[tuple[MarketType, FiscalQuarter], QuarterEps] = {}
        """The pages already held, which the stock page reads without a fetch."""

    async def load_page(self, market: MarketType, quarter: FiscalQuarter) -> QuarterEps | None:
        return self.held_pages.get((market, quarter))

    async def fetch_monthly_revenues(self, market: MarketType, year: int, month: int) -> list[MonthlyRevenue] | None:
        return self.monthly_revenue_summaries.get((market, year, month))

    async def fetch_cumulative_eps(self, quarters: Collection[FiscalQuarter]) -> EpsFilings:
        self.requested.append(set(quarters))
        return {
            quarter: None
            if quarter in self.failed_quarters
            else QuarterEps(
                quarter=quarter,
                cumulative_eps=dict(self.cumulative_eps.get(quarter, {})),
                fetched_at=self.fetched_at,
                refresh_failed=quarter in self.refresh_failed_quarters,
            )
            for quarter in quarters
        }


class FakeOhlcvProvider:
    """
    The price source in memory: each stock's bars as `history` holds them, served as the adjusted and as the listed
    history alike, TWSE's ex-right references in `references`, each index's bars and the realtime quotes.
    """

    def __init__(self) -> None:
        self.history: dict[str, list[Ohlcv]] = {}
        self.references: dict[str, dict[datetime, float]] = {}
        self.index_history: dict[MarketIndex, list[Ohlcv]] = {}
        self.realtime: dict[str, Ohlcv] = {}
        self.history_requests: list[str] = []
        self.realtime_requests: list[str] = []

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        self.history_requests.extend(stock.stock_id for stock in stocks)
        return {stock.stock_id: list(self.history[stock.stock_id]) for stock in stocks if stock.stock_id in self.history}

    async def fetch_index_history(self, index: MarketIndex, start_date: datetime, end_date: datetime) -> list[Ohlcv]:
        return list(self.index_history.get(index, []))

    async def held_span(self) -> tuple[date, date] | None:
        sessions = sorted({bar.ts.date() for bars in self.history.values() for bar in bars})
        return (sessions[0], sessions[-1]) if sessions else None

    async def listed_history(self) -> ListedHistory | None:
        if not any(self.history.values()):
            return None

        return ListedHistoryRule().apply(self.history, self.references, lambda stamp: stamp.date())

    async def listed_fingerprint(self) -> tuple[object, ...]:
        bars = tuple((stock_id, *bars) for stock_id, bars in self.history.items())
        return bars, tuple((stock_id, *days.items()) for stock_id, days in self.references.items())

    async def ex_right_references(self, first: date, last: date) -> dict[str, dict[datetime, float]]:
        return {stock_id: dict(days) for stock_id, days in self.references.items()}

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        self.realtime_requests.extend(stock.stock_id for stock in stocks)
        return {stock.stock_id: self.realtime[stock.stock_id] for stock in stocks if stock.stock_id in self.realtime}


class FakeNewsProvider:
    def __init__(self) -> None:
        self.articles: dict[str, list[Article]] = {}
        self.requested: list[str] = []
        self.failure: Exception | None = None

    async def fetch_news(self, stock_id: str, limit: int = 10) -> list[Article]:
        self.requested.append(stock_id)

        if self.failure is not None:
            raise self.failure

        return [replace(article) for article in self.articles.get(stock_id, [])[:limit]]

    def save_as_md_file(self, stock_id: str, articles: list[Article]) -> None:
        return None


class FakeSocialMediaProvider:
    def __init__(self) -> None:
        self.articles: list[Article] = []
        self.stock_posts: dict[str, list[Article]] = {}
        self.searched: list[str] = []

    async def fetch_stock_posts(self, stock_id: str, limit: int) -> list[Article]:
        self.searched.append(stock_id)
        return [replace(article) for article in self.stock_posts.get(stock_id, [])[:limit]]

    async def fetch_social_articles(self, limit: int) -> list[Article]:
        return [replace(article) for article in self.articles[:limit]]

    def save_social_media_data(self, articles: list[Article]) -> None:
        return None


@dataclass(frozen=True)
class AiCall:
    stock_id: str
    focus: AiAnalysisFocus | None
    """None for a valuation explanation."""

    prompt: str


class AiVendor:
    """
    A paid AI vendor behind a counted provider (DailyCappedAiProvider): it answers every call with `reply`, counts the
    calls and keeps the stock of each saved reply.
    """

    def __init__(self, reply: str = "{}") -> None:
        self.reply = reply
        self.calls = 0
        self.saved: list[str] = []

    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        self.calls += 1
        return Message(role=MessageRole.ASSISTANT, content=self.reply, timestamp=messages[-1].timestamp)

    def save_response(self, stock_id: str, content: str) -> None:
        self.saved.append(stock_id)


class FakeAiProvider:
    """
    Answers each prompt for the stock named in its header (PROMPT_TEMPLATES or VALUATION_PROMPT_TEMPLATE):
    an analysis prompt with the stock's score, a valuation prompt with the stock's valuation reply.
    """

    def __init__(self, default_score: int = 90) -> None:
        self.default_score = default_score
        self.scores: dict[str, int] = {}
        self.valuation_replies: dict[str, dict] = {}
        self.failures: dict[str, Exception] = {}
        self.calls: list[AiCall] = []
        self.chat_reply: str | None = None
        self.chat_conversations: list[tuple[Message, ...]] = []

    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        header = PROMPT_HEADER.match(messages[-1].content)

        if header is None and self.chat_reply is not None:
            self.chat_conversations.append(messages)
            return Message(role=MessageRole.ASSISTANT, content=self.chat_reply, timestamp=messages[-1].timestamp)

        assert header is not None, f"prompt does not start with a known template header: {messages[-1].content!r}"
        kind, stock_id = header.group(1), header.group(2)
        focus = None if kind == "valuation explanation" else AiAnalysisFocus(kind.split()[0])
        self.calls.append(AiCall(stock_id=stock_id, focus=focus, prompt=messages[-1].content))

        if stock_id in self.failures:
            raise self.failures[stock_id]

        if focus is None:
            reply = self.valuation_replies.get(
                stock_id,
                {
                    "higher_pe_factors": [f"fake factor for {stock_id}"],
                    "pe_derating_risks": [f"fake risk for {stock_id}"],
                    "data_gaps": [],
                    "summary": f"fake valuation explanation of {stock_id}",
                },
            )
            return Message(role=MessageRole.ASSISTANT, content=json.dumps(reply), timestamp=messages[-1].timestamp)

        report = {
            "confidence_score": self.scores.get(stock_id, self.default_score),
            "summary": f"fake analysis of {stock_id}",
            "bullish_factors": [],
            "bearish_factors": [],
        }
        return Message(role=MessageRole.ASSISTANT, content=json.dumps(report), timestamp=messages[-1].timestamp)

    def save_response(self, stock_id: str, content: str) -> None:
        return None

    @property
    def analysed_stock_ids(self) -> list[str]:
        return [call.stock_id for call in self.calls]


class FakeKnowledgeRepository:
    def __init__(self) -> None:
        self.decisions: list[tuple[str, TradeSignal]] = []

    async def find_decision_history(self, stock_id: str, limit: int = 3) -> str:
        return ""

    async def save_decision(self, stock: Stock, signal: TradeSignal) -> None:
        self.decisions.append((stock.stock_id, signal))


class FakeConversationRepository:
    def __init__(self) -> None:
        self.conversations: dict[str, Conversation] = {}

    async def get_conversation_by_user_id(self, user_id: str) -> Conversation | None:
        return self.conversations.get(user_id)

    async def save(self, conversation: Conversation) -> bool:
        self.conversations[conversation.user_id] = conversation
        return True


class RecordingChatPlatform:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_message(self, user_id: str, message: Message) -> bool:
        self.sent.append((user_id, message.content))
        return True


@dataclass
class FakeTradingJournal:
    """Holds what TradingJournal writes: one row per run, decision, order and snapshot, upserted by key."""

    runs: dict[RunId, SystemStats] = field(default_factory=dict)
    signals: list[TradeSignal] = field(default_factory=list)
    signal_runs: dict[DecisionId, RunId] = field(default_factory=dict)
    orders: dict[UUID, Order] = field(default_factory=dict)
    account_snapshots: list[AccountSnapshot] = field(default_factory=list)
    stock_reports: dict[RunId, list[RunStockReportDTO]] = field(default_factory=dict)

    async def save_run(self, run: SystemStats) -> None:
        self.runs[run.run_id] = replace(run)

    async def save_signals(self, run_id: RunId, signals: list[TradeSignal]) -> None:
        for signal in signals:
            self.signals.append(signal)
            self.signal_runs[signal.decision_id] = run_id

    async def save_order(self, order: Order) -> None:
        self.orders[order.id] = replace(order)

    async def save_snapshot(self, snapshot: AccountSnapshot) -> None:
        self.account_snapshots.append(snapshot)

    def on(self, broker: ExecutionProvider, run_id: RunId) -> bool:
        """Whether the run of `run_id` chose `broker`, as the SQL journal reads a row's broker through its run."""
        run = self.runs.get(run_id)
        return run is not None and run.execution_provider == broker

    async def snapshots(self, broker: ExecutionProvider, since: datetime | None = None) -> list[AccountSnapshot]:
        kept = [
            snapshot
            for snapshot in self.account_snapshots
            if self.on(broker, snapshot.run_id) and (since is None or snapshot.taken_at >= since)
        ]
        return sorted(kept, key=lambda snapshot: snapshot.taken_at)

    async def save_stock_reports(self, run_id: RunId, stocks: list[Stock]) -> None:
        """Keeps each stock as the SQL journal stores it, so a later change to the Stock object is not seen."""
        self.stock_reports[run_id] = [
            RunStockReportDTO.from_domain(run_id, position, stock, "fake") for position, stock in enumerate(stocks)
        ]

    async def stock_reports_of(self, run_id: RunId) -> list[Stock]:
        return [row.to_domain() for row in self.stock_reports.get(run_id, [])]

    async def recent_runs(self, limit: int, offset: int = 0) -> list[SystemStats]:
        return sorted(self.runs.values(), key=lambda run: run.start_time, reverse=True)[offset : offset + limit]

    async def find_run(self, run_id: RunId) -> SystemStats | None:
        return self.runs.get(run_id)

    async def signals_of(self, run_id: RunId) -> list[TradeSignal]:
        return [signal for signal in self.signals if self.signal_runs[signal.decision_id] == run_id]

    async def orders_of(self, run_id: RunId) -> list[Order]:
        return [order for order in self.orders.values() if order.run_id == run_id]

    async def follows_of(self, run_id: RunId) -> list[tuple[TradeSignal, Order]]:
        followed = {signal.decision_id for signal in await self.signals_of(run_id)}
        orders = {order.decision_id: order for order in self.orders.values()}
        follows = [(signal, orders[signal.decision_id]) for signal in self.signals if signal.followed_decision_id in followed]
        return sorted((follow for follow in follows if follow[0].decision_id in orders), key=lambda follow: follow[1].created_at)

    async def trades(
        self, broker: ExecutionProvider, since: datetime | None, limit: int, offset: int
    ) -> list[tuple[Order, SystemStats]]:
        filled = [
            order
            for order in self.orders.values()
            if order.filled_quantity > 0 and self.on(broker, order.run_id) and (since is None or order.created_at >= since)
        ]
        newest = sorted(filled, key=lambda order: order.created_at, reverse=True)[offset : offset + limit]
        runs = {order.run_id: self.runs[order.run_id] for order in newest}
        sources = {run_id: self.runs.get(run.followed_run_id, run) if run.followed_run_id else run for run_id, run in runs.items()}
        return [(order, sources[order.run_id]) for order in newest]

    async def first_fill(self, workflow: Workflow, broker: ExecutionProvider, since: datetime | None) -> datetime | None:
        filled = [
            order.created_at
            for order in self.orders.values()
            if order.filled_quantity > 0
            and self.on(broker, order.run_id)
            and self.runs[order.run_id].workflow == workflow
            and (since is None or order.created_at >= since)
        ]
        return min(filled, default=None)

    async def buy_orders(self, broker: ExecutionProvider, since: datetime) -> list[Order]:
        orders = [
            order
            for order in self.orders.values()
            if order.action == TradeAction.BUY and self.on(broker, order.run_id) and order.created_at >= since
        ]
        return sorted(orders, key=lambda order: order.created_at)


class FakeWatchlistRepository:
    """Holds one entry per (stock_id, type), like the watchlists table, and returns the entries not expired at the clock's time."""

    def __init__(self, clock: FakeMarketClock) -> None:
        self._clock = clock
        self.entries: dict[tuple[str, WatchlistType], WatchlistEntry] = {}

    @property
    def rows(self) -> list[tuple[str, WatchlistType]]:
        return list(self.entries)

    async def get_active(self) -> list[WatchlistEntry]:
        now = self._clock.now()
        return [entry for entry in self.entries.values() if entry.expires_at is None or entry.expires_at > now]

    async def save(self, entries: list[WatchlistEntry]) -> None:
        for entry in entries:
            self.entries[(entry.stock_id, entry.watchlist_type)] = entry

    async def remove(self, stock_ids: list[str], watchlist_type: WatchlistType) -> list[str]:
        removed = [stock_id for stock_id in stock_ids if self.entries.pop((stock_id, watchlist_type), None) is not None]
        return removed


class FakeHoldingRepository:
    """Holds one hand-entered holding per stock, like one owner's rows of the manual_holdings table."""

    def __init__(self) -> None:
        self.holdings: dict[str, Position] = {}

    async def get_all(self) -> list[Position]:
        return [replace(self.holdings[stock_id]) for stock_id in sorted(self.holdings)]

    async def save(self, position: Position) -> None:
        self.holdings[position.stock_id] = replace(position)

    async def remove(self, stock_id: str) -> bool:
        return self.holdings.pop(stock_id, None) is not None


class FakeSentimentClassifier:
    """Labels every post with the label set for its stock and records which posts each stock sent."""

    def __init__(self) -> None:
        self.labels: dict[str, SentimentLabel] = {}
        self.classified: list[tuple[str, list[str]]] = []

    async def classify(self, stock_id: str, posts: list[Article]) -> list[Article]:
        self.classified.append((stock_id, [post.title for post in posts]))
        label = self.labels.get(stock_id, SentimentLabel.NEUTRAL)
        return [replace(post, sentiment=label, sentiment_confidence=0.9) for post in posts]


class RecordingExecutionProvider:
    """
    Broker that records each place_order call and fills it in full at its limit, charging fees like the mock. Its
    `link` says which broker it stands for: the mock account unless a test makes it SinoPac.
    """

    def __init__(self, cash: float = 1_000_000.0, cost_rule: TradingCostRule | None = None, link: BrokerLink | None = None) -> None:
        self.current_link = link or BrokerLink(broker=ExecutionProvider.MOCK)
        self.cash = cash
        self.opening: AccountOpening | None = None
        self.positions: list[Position] = []
        self.settlements: list[Settlement] = []
        self.fills: list[BrokerFill] = []
        self.sales: list[BrokerFill] = []
        self.placed: list[Order] = []
        self._cost_rule = cost_rule or TradingCostRule(
            fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20, bond_etf_tax_exempt_until=date(2026, 12, 31)
        )

    def link(self) -> BrokerLink:
        return self.current_link

    async def place_order(self, order: Order, refusal_now: SendRefusal) -> Order:
        if (refusal := await refusal_now()) is not None:
            order.reject(*refusal, now=datetime.now(UTC))
            return order

        self.placed.append(replace(order))
        assert order.limit_price is not None, "the app sends LIMIT orders only"

        cost = self._cost_rule.apply(order.action, order.stock_id, order.limit_price, order.quantity, now=datetime.now(UTC))
        held = next((position for position in self.positions if position.stock_id == order.stock_id), None)
        realized_pnl = held.profit_on_sale(order.quantity, cost.net) if order.action == TradeAction.SELL and held else None

        order.submit(now=datetime.now(UTC))
        order.fill(order.quantity, order.limit_price, cost.fee, cost.tax, realized_pnl, now=datetime.now(UTC))
        return order

    async def get_account(self) -> Account:
        return Account(cash=self.cash, positions=[replace(position) for position in self.positions], opening=self.opening)

    async def open_positions(self) -> list[Position]:
        return [replace(position) for position in self.positions]

    async def statement(self, sales_from: date, today: date) -> BrokerageStatement:
        """A real broker's own report of the account: the positions as held, and the fills and sales a test set."""
        return BrokerageStatement(
            read_at=datetime.now(UTC),
            simulation=bool(self.current_link.simulation),
            balance=self.cash,
            settlements=list(self.settlements),
            positions=await self.open_positions(),
            fills=[fill for fill in self.fills if fill.filled_on == today],
            sales=[sale for sale in self.sales if sales_from <= sale.filled_on <= today],
            sales_from=sales_from,
        )

    async def reset(self, initial_cash: float, now: datetime) -> Account:
        self.cash, self.positions, self.opening = initial_cash, [], AccountOpening(initial_cash=initial_cash, opened_at=now)
        return await self.get_account()


class FakeBacktestRepository:
    """Like the SQL repository built for one owner: the owner's backtests, the newest `keep` after each save."""

    def __init__(self) -> None:
        self.backtests: list[Backtest] = []

    async def save(self, backtest: Backtest, keep: int) -> None:
        self.backtests = sorted([*self.backtests, backtest], key=lambda saved: saved.created_at, reverse=True)[:keep]

    async def saved(self) -> list[Backtest]:
        return list(self.backtests)

    async def get(self, backtest_id: BacktestId) -> Backtest | None:
        return next((backtest for backtest in self.backtests if backtest.backtest_id == backtest_id), None)

    async def delete(self, backtest_id: BacktestId) -> bool:
        kept = [backtest for backtest in self.backtests if backtest.backtest_id != backtest_id]
        deleted, self.backtests = len(kept) < len(self.backtests), kept
        return deleted


class FakeStockBriefRepository:
    """Like the SQL repository: one brief per stock and day, a claim one caller takes, and a limit on a day's stocks."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, date], StockBrief] = {}

    async def find(self, stock_id: str, day: date) -> StockBrief | None:
        held = self.rows.get((stock_id, day))
        return replace(held) if held is not None else None

    async def latest_written(self, stock_id: str, before: date) -> StockBrief | None:
        written = [
            brief
            for (held_id, day), brief in self.rows.items()
            if held_id == stock_id and day < before and brief.status == BriefStatus.WRITTEN
        ]
        return max(written, key=lambda brief: brief.day, default=None)

    async def claimed_stocks(self, day: date) -> int:
        return sum(held_day == day for _, held_day in self.rows)

    async def claim(self, brief: StockBrief, daily_stocks: int, stale_before: datetime) -> bool:
        held = self.rows.get((brief.stock_id, brief.day))
        abandoned = held is not None and held.status == BriefStatus.WRITING and held.claimed_at < stale_before
        free = held is None and await self.claimed_stocks(brief.day) < daily_stocks

        if not (free or abandoned or (held is not None and held.status == BriefStatus.FAILED)):
            return False

        self.rows[(brief.stock_id, brief.day)] = replace(brief)
        return True

    async def save(self, brief: StockBrief) -> None:
        self.rows[(brief.stock_id, brief.day)] = replace(brief)

    async def release(self, stock_id: str, day: date) -> None:
        self.rows.pop((stock_id, day), None)


class FakeTextEmbedder:
    """
    ITextEmbedder without a model: a text's vector counts its pairs of neighbouring characters in `SIZE` buckets, so
    texts that share wording lie close. It keeps every text it embedded, so a test can see what was embedded again.
    """

    SIZE = 64

    def __init__(self) -> None:
        self.embedded: list[str] = []
        self.failure: Exception | None = None

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self.embed_batch(texts)

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        self.load()
        self.embedded.extend(texts)
        vectors = []

        for text in texts:
            counts = [0.0] * self.SIZE

            for pair in itertools.pairwise(text):
                counts[zlib.crc32("".join(pair).encode()) % self.SIZE] += 1

            length = math.sqrt(sum(count * count for count in counts)) or 1.0
            vectors.append([count / length for count in counts])

        return vectors

    def load(self) -> None:
        if self.failure is not None:
            raise self.failure


class FakeArticleStore:
    """Like the SQL store: one article per stock and key, replaced only when its title or text changed, within retention."""

    def __init__(self, clock: IMarketClock, retention: timedelta, max_per_stock: int) -> None:
        self.clock = clock
        self.retention = retention
        self.max_per_stock = max_per_stock
        self.rows: dict[tuple[str, str], Article] = {}

    async def save(self, articles: Sequence[Article]) -> int:
        now = self.clock.now()
        changed = 0

        for article in articles:
            held = self.rows.get((article.stock_id, article.key))

            if article.published_at >= now - self.retention and (
                held is None or (held.title, held.content) != (article.title, article.content)
            ):
                self.rows[(article.stock_id, article.key)] = replace(article, fetched_at=now)
                changed += 1

        kept = {place: article for place, article in self.rows.items() if article.published_at >= now - self.retention}
        self.rows = {
            (article.stock_id, article.key): article
            for stock_id in {stock_id for stock_id, _ in kept}
            for article in sorted(
                (article for article in kept.values() if article.stock_id == stock_id),
                key=lambda article: article.published_at,
                reverse=True,
            )[: self.max_per_stock if any(given.stock_id == stock_id for given in articles) else None]
        }
        return changed

    async def latest(self, stock_id: str, limit: int) -> list[Article]:
        held = [article for (held_id, _), article in self.rows.items() if held_id == stock_id]
        return [replace(article) for article in sorted(held, key=lambda article: article.published_at, reverse=True)[:limit]]

    async def find(self, stock_id: str, keys: Collection[str]) -> list[Article]:
        return [replace(article) for (held_id, key), article in self.rows.items() if held_id == stock_id and key in keys]

    async def stock_ids(self) -> list[str]:
        return sorted({stock_id for stock_id, _ in self.rows})


class FakeArticleIndex:
    """Like the Chroma index: a vector per stock and key with its day and its text, embedded only when the text is new."""

    def __init__(self, embedder: FakeTextEmbedder, text_length: int = 300) -> None:
        self.embedder = embedder
        self.text_length = text_length
        self.entries: dict[tuple[str, str], tuple[str, date, list[float]]] = {}

    async def sync(self, stock_id: str, articles: Sequence[Article]) -> int:
        wanted = {article.key: (self.embedded_text(article), article.published_at.date()) for article in articles}
        missing = [key for key, described in wanted.items() if self.entries.get((stock_id, key), ("", None, []))[:2] != described]
        vectors = await self.embedder.embed([wanted[key][0] for key in missing]) if missing else []
        self.entries = {place: entry for place, entry in self.entries.items() if place[0] != stock_id or place[1] in wanted}
        self.entries.update({(stock_id, key): (*wanted[key], vector) for key, vector in zip(missing, vectors, strict=True)})
        return len(missing)

    async def search(self, stock_id: str, query: str, first: date | None, last: date | None, limit: int) -> list[str]:
        asked = (await self.embedder.embed([query]))[0]
        within = {
            key: sum(left * right for left, right in zip(asked, vector, strict=True))
            for (held_id, key), (_, day, vector) in self.entries.items()
            if held_id == stock_id and (first is None or day >= first) and (last is None or day < last)
        }
        return sorted(within, key=lambda key: within[key], reverse=True)[:limit]

    def embedded_text(self, article: Article) -> str:
        text = article.content[: self.text_length]
        return article.title if not text or text == article.title else f"{article.title}\n{text}"


class FakeUsersStocks:
    """The stocks some user holds or watches, as a test sets them."""

    def __init__(self) -> None:
        self.stock_ids: set[str] = set()

    async def held_or_watched(self) -> set[str]:
        return set(self.stock_ids)


class FakeTechnicalSettingsRepository:
    """
    Like the SQL repository built for one owner: the saved settings, the initial ones saved on the first load, and a
    save refused, changing nothing, when the revision it carries is no longer the saved one. The next
    interrupted_loads loads fail as a load does when a save lands between its reads.
    """

    def __init__(self, saved: TechnicalSettings | None = None) -> None:
        self.saved = saved
        self.interrupted_loads = 0

    async def load(self, initial: TechnicalSettings) -> TechnicalSettings:
        if self.interrupted_loads:
            self.interrupted_loads -= 1
            raise TechnicalSettingsConflictError("The technical settings changed while being read. Read them again.")

        if self.saved is None:
            self.saved = replace(initial, revision=0)

        return self.saved

    async def save(self, settings: TechnicalSettings) -> TechnicalSettings:
        if self.saved is None or self.saved.revision != settings.revision:
            raise TechnicalSettingsConflictError("The technical settings changed after they were read.")

        self.saved = replace(settings, revision=settings.revision + 1)
        return self.saved


class FakeUserStore:
    """
    Like SqlUserStore, in memory: names unique and found without regard to case, sessions by token, a deactivated user
    signed out, and the last active administrator kept. It keeps passwords in the clear: it is a fake.
    """

    def __init__(self) -> None:
        self.by_id: dict[UserId, User] = {}
        self.passwords: dict[UserId, str | None] = {}
        self.sessions: dict[SessionToken, UserSession] = {}
        self.session_numbers = itertools.count(1)
        """An ended session's token never names a later one."""

    def add(self, user: User, password: str | None) -> None:
        self.by_id[user.user_id] = replace(user, has_password=password is not None)
        self.passwords[user.user_id] = password

    def named(self, identifier: str) -> User | None:
        name = comparable_name(identifier)
        return next(
            (user for user in self.by_id.values() if name in (comparable_name(user.username), comparable_name(user.email))), None
        )

    async def check_key(self) -> None:
        return None

    async def user_count(self) -> int:
        return len(self.by_id)

    async def create(self, user: User, password: SecretStr | None) -> None:
        if user.user_id in self.by_id:
            raise AlreadySetUpError(f"User {user.user_id} exists.")

        for taken in ("username", "email"):
            if any(getattr(other, taken).casefold() == getattr(user, taken).casefold() for other in self.by_id.values()):
                raise UserExistsError(taken)

        self.add(user, password.get_secret_value() if password is not None else None)

    async def verify_password(self, identifier: str, password: SecretStr) -> User | None:
        user = self.named(identifier)
        matches = user is not None and self.passwords[user.user_id] == password.get_secret_value()
        return replace(user) if user is not None and matches and user.status == UserStatus.ACTIVE else None

    async def find_by_name(self, identifier: str) -> User | None:
        user = self.named(identifier)
        return replace(user) if user is not None else None

    async def open_session(self, user_id: UserId, now: datetime, expires_at: datetime) -> UserSession:
        session = UserSession(
            token=SessionToken(f"session-{next(self.session_numbers)}-{user_id}"),
            user_id=user_id,
            created_at=now,
            expires_at=expires_at,
        )
        self.sessions[session.token] = session
        return session

    async def session_user(self, token: SessionToken, now: datetime) -> User | None:
        session = self.sessions.get(token)
        user = self.by_id.get(session.user_id) if session is not None and session.expires_at > now else None
        return replace(user) if user is not None and user.status == UserStatus.ACTIVE else None

    async def close_session(self, token: SessionToken) -> None:
        self.sessions.pop(token, None)

    async def users(self) -> list[User]:
        return [replace(user) for user in sorted(self.by_id.values(), key=lambda user: user.created_at)]

    async def find(self, user_id: UserId) -> User | None:
        user = self.by_id.get(user_id)
        return replace(user) if user is not None else None

    async def save(self, user: User, now: datetime, password: SecretStr | None = None) -> None:
        after = {**self.by_id, user.user_id: user}

        if not any(other.role == Role.ADMINISTRATOR and other.status == UserStatus.ACTIVE for other in after.values()):
            raise LastAdministratorError("At least one active administrator must remain. Nothing was saved.")

        kept = self.passwords[user.user_id] if user.has_password else None
        new_password = password.get_secret_value() if password is not None else kept
        changed = password is not None or new_password != self.passwords[user.user_id]
        self.by_id[user.user_id] = replace(user, ai_model=self.by_id[user.user_id].ai_model, has_password=new_password is not None)
        self.passwords[user.user_id] = new_password

        if user.status != UserStatus.ACTIVE or changed:
            self.sessions = {token: session for token, session in self.sessions.items() if session.user_id != user.user_id}

    async def save_ai_model(self, user_id: UserId, ai_model: AiProvider | None, now: datetime) -> None:
        if user_id in self.by_id:
            self.by_id[user_id] = replace(self.by_id[user_id], ai_model=ai_model)


class SignedOut:
    """
    A port of a signed-out pipeline that holds a user's data: any call raises SignInRequired, as the adapters do, from a
    coroutine for the port's async methods and at once for its plain ones.
    """

    def __init__(self, port: type) -> None:
        self.port = port

    def __getattr__(self, name: str):
        def refuse(*args, **kwargs):
            raise SignInRequired(f"{self.port.__name__}.{name} needs a signed-in user.")

        async def refuse_later(*args, **kwargs):
            refuse()

        return refuse_later if inspect.iscoroutinefunction(getattr(self.port, name)) else refuse


class FakeOrderingSwitch:
    """The ordering switch of a site whose settings files hold `features`: what the real one reads from disk at each ask."""

    def __init__(self, features: FeaturesConfig) -> None:
        self.features = features

    async def visibility(self, broker: ExecutionProvider) -> FeatureVisibility:
        return self.features.ordering()[broker]


async def no_refusal() -> None:
    """The send-time question of a test that sends straight to a broker: nothing refuses the exchange order."""
    return None
