"""Fakes for the Protocols in a_domain/ports.

Each fake answers like its real adapter and records what the outside system
behind that port would observe: rows written, prompts sent, orders placed.
"""

import inspect
import json
import re
from collections.abc import Collection
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import SecretStr

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
from a_domain.model.trading.account import Account, AccountSnapshot, Position
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
from a_domain.rules.fundamentals.trailing_eps import EpsFilings, QuarterEps
from a_domain.rules.technical.strategy import TechnicalSettings
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.types.enums import (
    AiAnalysisFocus,
    AiProvider,
    FinancialStatement,
    MarketIndex,
    MarketType,
    MessageRole,
    Role,
    SentimentLabel,
    TradeAction,
    UserStatus,
    WatchlistType,
)
from a_domain.types.errors import (
    AlreadySetUpError,
    LastAdministratorError,
    SignInRequired,
    TechnicalSettingsConflictError,
    UserExistsError,
)
from a_domain.types.ids import DecisionId, RunId, SessionToken, UserId
from a_domain.types.values import FiscalQuarter, comparable_name
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

    def save_as_md_file(self, stock_id: str, articles: list[Article]) -> None:
        return None


class FakeFundamentalsProvider:
    """MOPS stand-in: cumulative EPS filed per quarter, quarters that fail to fetch, and quarters whose refresh failed."""

    def __init__(self) -> None:
        self.cumulative_eps: dict[FiscalQuarter, dict[str, float]] = {}
        self.failed_quarters: set[FiscalQuarter] = set()
        self.refresh_failed_quarters: set[FiscalQuarter] = set()
        self.requested: list[set[FiscalQuarter]] = []
        self.fetched_at = datetime(2026, 10, 19, 18, 0)

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
    def __init__(self) -> None:
        self.history: dict[str, list[Ohlcv]] = {}
        self.index_history: dict[MarketIndex, list[Ohlcv]] = {}
        self.realtime: dict[str, Ohlcv] = {}
        self.history_requests: list[str] = []
        self.realtime_requests: list[str] = []

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        self.history_requests.extend(stock.stock_id for stock in stocks)
        return {stock.stock_id: list(self.history[stock.stock_id]) for stock in stocks if stock.stock_id in self.history}

    async def fetch_index_history(self, index: MarketIndex, start_date: datetime, end_date: datetime) -> list[Ohlcv]:
        return list(self.index_history.get(index, []))

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        self.realtime_requests.extend(stock.stock_id for stock in stocks)
        return {stock.stock_id: self.realtime[stock.stock_id] for stock in stocks if stock.stock_id in self.realtime}


class FakeNewsProvider:
    def __init__(self) -> None:
        self.articles: dict[str, list[Article]] = {}
        self.requested: list[str] = []

    async def fetch_news(self, stock_id: str, limit: int = 10) -> list[Article]:
        self.requested.append(stock_id)
        return [replace(article) for article in self.articles.get(stock_id, [])[:limit]]

    def save_as_md_file(self, stock_id: str, articles: list[Article]) -> None:
        return None


class FakeSocialMediaProvider:
    def __init__(self) -> None:
        self.articles: list[Article] = []

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

    async def snapshots(self) -> list[AccountSnapshot]:
        return sorted(self.account_snapshots, key=lambda snapshot: snapshot.taken_at)

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
    """Broker that records each place_order call and fills it in full at its limit, charging fees like the mock."""

    def __init__(self, cash: float = 1_000_000.0, cost_rule: TradingCostRule | None = None) -> None:
        self.cash = cash
        self.positions: list[Position] = []
        self.placed: list[Order] = []
        self.closed = False
        self._cost_rule = cost_rule or TradingCostRule(
            fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20, bond_etf_tax_exempt_until=date(2026, 12, 31)
        )

    async def place_order(self, order: Order) -> Order:
        self.placed.append(replace(order))
        assert order.limit_price is not None, "the app sends LIMIT orders only"

        cost = self._cost_rule.apply(order.action, order.stock_id, order.limit_price, order.quantity, now=datetime.now(UTC))
        held = next((position for position in self.positions if position.stock_id == order.stock_id), None)
        realized_pnl = held.profit_on_sale(order.quantity, cost.net) if order.action == TradeAction.SELL and held else None

        order.submit(now=datetime.now(UTC))
        order.fill(order.quantity, order.limit_price, cost.fee, cost.tax, realized_pnl, now=datetime.now(UTC))
        return order

    async def get_account(self) -> Account:
        return Account(cash=self.cash, positions=[replace(position) for position in self.positions])

    async def close(self) -> None:
        self.closed = True


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
        self.passwords: dict[UserId, str] = {}
        self.sessions: dict[SessionToken, UserSession] = {}

    def add(self, user: User, password: str) -> None:
        self.by_id[user.user_id] = replace(user)
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

    async def create(self, user: User, password: SecretStr) -> None:
        if user.user_id in self.by_id:
            raise AlreadySetUpError(f"User {user.user_id} exists.")

        for taken in ("username", "email"):
            if any(getattr(other, taken).casefold() == getattr(user, taken).casefold() for other in self.by_id.values()):
                raise UserExistsError(taken)

        self.add(user, password.get_secret_value())

    async def verify_password(self, identifier: str, password: SecretStr) -> User | None:
        user = self.named(identifier)
        matches = user is not None and self.passwords[user.user_id] == password.get_secret_value()
        return replace(user) if user is not None and matches and user.status == UserStatus.ACTIVE else None

    async def find_by_name(self, identifier: str) -> User | None:
        user = self.named(identifier)
        return replace(user) if user is not None else None

    async def open_session(self, user_id: UserId, now: datetime, expires_at: datetime) -> UserSession:
        session = UserSession(
            token=SessionToken(f"session-{len(self.sessions) + 1}-{user_id}"), user_id=user_id, created_at=now, expires_at=expires_at
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

        self.by_id[user.user_id] = replace(user, ai_model=self.by_id[user.user_id].ai_model)

        if password is not None:
            self.passwords[user.user_id] = password.get_secret_value()

        if user.status != UserStatus.ACTIVE or password is not None:
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
