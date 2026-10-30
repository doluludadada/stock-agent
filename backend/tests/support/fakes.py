"""Fakes for the Protocols in a_domain/ports.

Each fake answers like its real adapter and records what the outside system
behind that port would observe: rows written, prompts sent, orders placed.
"""

import json
import re
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from a_domain.model.analysis.social_sentiment import SentimentClassification
from a_domain.model.analysis.technical_settings import TechnicalSettings
from a_domain.model.chat.message import Message
from a_domain.model.fundamentals.eps import EpsFilings, FiscalQuarter, QuarterEps
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account
from a_domain.model.trading.account_snapshot import AccountSnapshot
from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.types.enums import AiAnalysisFocus, MessageRole, SentimentLabel, TradeAction, WatchlistType
from a_domain.types.ids import DecisionId, RunId
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
    """Taiwan-time clock whose current time and market session are set by the test."""

    def __init__(self, now: datetime, market_open: bool) -> None:
        self.current_time = now
        self.market_open = market_open

    def now(self) -> datetime:
        return self.current_time

    def is_market_open(self) -> bool:
        return self.market_open


class FakeStockProvider:
    """Like TaiwanStockProvider, every call returns new copies of the listed stocks, as IStockProvider promises."""

    def __init__(self) -> None:
        self.stocks: dict[str, Stock] = {}
        self.closes: dict[str, Ohlcv] = {}

    async def get_all(self) -> list[Stock]:
        return [stock.model_copy(deep=True) for stock in self.stocks.values()]

    async def get_by_id(self, stock_id: str) -> Stock | None:
        stock = self.stocks.get(stock_id)
        return stock.model_copy(deep=True) if stock is not None else None

    async def get_latest_closes(self) -> dict[str, Ohlcv]:
        return {stock_id: bar.model_copy() for stock_id, bar in self.closes.items()}


class FakeFundamentalsProvider:
    """MOPS stand-in: cumulative EPS filed per quarter, industries, and quarters that fail to fetch."""

    def __init__(self) -> None:
        self.cumulative_eps: dict[FiscalQuarter, dict[str, float]] = {}
        self.industries: dict[str, str] = {}
        self.failed_quarters: set[FiscalQuarter] = set()
        self.requested: list[set[FiscalQuarter]] = []
        self.fetched_at = datetime(2026, 10, 19, 18, 0)

    async def fetch_cumulative_eps(self, quarters: Collection[FiscalQuarter]) -> EpsFilings:
        self.requested.append(set(quarters))
        return {
            quarter: None
            if quarter in self.failed_quarters
            else QuarterEps(quarter=quarter, cumulative_eps=dict(self.cumulative_eps.get(quarter, {})), fetched_at=self.fetched_at)
            for quarter in quarters
        }

    async def fetch_industries(self) -> dict[str, str]:
        return dict(self.industries)


class FakeOhlcvProvider:
    def __init__(self) -> None:
        self.history: dict[str, list[Ohlcv]] = {}
        self.realtime: dict[str, Ohlcv] = {}
        self.history_requests: list[str] = []
        self.realtime_requests: list[str] = []

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        self.history_requests.extend(stock.stock_id for stock in stocks)
        return {
            stock.stock_id: [bar.model_copy() for bar in self.history[stock.stock_id]]
            for stock in stocks
            if stock.stock_id in self.history
        }

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        self.realtime_requests.extend(stock.stock_id for stock in stocks)
        return {stock.stock_id: self.realtime[stock.stock_id].model_copy() for stock in stocks if stock.stock_id in self.realtime}


class FakeNewsProvider:
    def __init__(self) -> None:
        self.articles: dict[str, list[Article]] = {}
        self.requested: list[str] = []

    async def fetch_news(self, stock_id: str, limit: int = 10) -> list[Article]:
        self.requested.append(stock_id)
        return [article.model_copy() for article in self.articles.get(stock_id, [])[:limit]]

    def save_as_md_file(self, stock_id: str, articles: list[Article]) -> None:
        return None


class FakeSocialMediaProvider:
    def __init__(self) -> None:
        self.articles: list[Article] = []

    async def fetch_social_articles(self, limit: int) -> list[Article]:
        return [article.model_copy() for article in self.articles[:limit]]

    def save_social_media_data(self, articles: list[Article]) -> None:
        return None


@dataclass(frozen=True)
class AiCall:
    stock_id: str
    focus: AiAnalysisFocus | None
    """None for a valuation explanation."""

    prompt: str


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

    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        header = PROMPT_HEADER.match(messages[-1].content)
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
            return Message(role=MessageRole.ASSISTANT, content=json.dumps(reply))

        report = {
            "confidence_score": self.scores.get(stock_id, self.default_score),
            "summary": f"fake analysis of {stock_id}",
            "bullish_factors": [],
            "bearish_factors": [],
        }
        return Message(role=MessageRole.ASSISTANT, content=json.dumps(report))

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


@dataclass
class FakeTradingJournal:
    """Holds what TradingJournal writes: one row per run, decision, order and snapshot, upserted by key."""

    runs: dict[RunId, SystemStats] = field(default_factory=dict)
    signals: list[TradeSignal] = field(default_factory=list)
    signal_runs: dict[DecisionId, RunId] = field(default_factory=dict)
    orders: dict[UUID, Order] = field(default_factory=dict)
    account_snapshots: list[AccountSnapshot] = field(default_factory=list)

    async def save_run(self, run: SystemStats) -> None:
        self.runs[run.run_id] = run.model_copy(deep=True)

    async def save_signals(self, run_id: RunId, signals: list[TradeSignal]) -> None:
        for signal in signals:
            self.signals.append(signal.model_copy())
            self.signal_runs[signal.decision_id] = run_id

    async def save_order(self, order: Order) -> None:
        self.orders[order.id] = order.model_copy()

    async def save_snapshot(self, snapshot: AccountSnapshot) -> None:
        self.account_snapshots.append(snapshot.model_copy(deep=True))

    async def snapshots(self) -> list[AccountSnapshot]:
        return sorted(self.account_snapshots, key=lambda snapshot: snapshot.taken_at)


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

    async def remove(self, stock_id: str) -> None:
        self.entries = {key: entry for key, entry in self.entries.items() if entry.stock_id != stock_id}


class FakeSentimentClassifier:
    """Labels every post with the label set for its stock and records which posts each stock sent."""

    def __init__(self) -> None:
        self.labels: dict[str, SentimentLabel] = {}
        self.classified: list[tuple[str, list[str]]] = []

    async def classify(self, stock_id: str, articles: list[Article]) -> list[SentimentClassification]:
        self.classified.append((stock_id, [article.title for article in articles]))
        label = self.labels.get(stock_id, SentimentLabel.NEUTRAL)
        return [SentimentClassification(label=label, confidence=0.9) for _ in articles]


class RecordingExecutionProvider:
    """Broker that records each place_order call and fills it in full at its limit, charging fees like the mock."""

    def __init__(self, cash: float = 1_000_000.0, cost_rule: TradingCostRule | None = None) -> None:
        self.cash = cash
        self.positions: list[Position] = []
        self.placed: list[Order] = []
        self._cost_rule = cost_rule or TradingCostRule(fee_rate=0.001425, tax_rate=0.003, min_fee=20)

    async def place_order(self, order: Order) -> Order:
        self.placed.append(order.model_copy())
        assert order.limit_price is not None, "the app sends LIMIT orders only"

        cost = self._cost_rule.cost_of(order.action, order.limit_price, order.quantity)
        held = next((position for position in self.positions if position.stock_id == order.stock_id), None)
        realized_pnl = held.profit_on_sale(order.quantity, cost.net) if order.action == TradeAction.SELL and held else None

        order.submit()
        order.fill(order.quantity, order.limit_price, cost, realized_pnl)
        return order

    async def get_account(self) -> Account:
        return Account(cash=self.cash, positions=[position.model_copy() for position in self.positions])


class FakeTechnicalSettingsRepository:
    def __init__(self, settings: TechnicalSettings) -> None:
        self.settings = settings

    async def load(self) -> TechnicalSettings:
        return self.settings

    async def save(self, settings: TechnicalSettings) -> None:
        self.settings = settings
