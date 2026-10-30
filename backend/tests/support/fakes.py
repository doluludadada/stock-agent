"""Fakes for the Protocols in a_domain/ports.

Each fake answers like its real adapter and records what the outside system
behind that port would observe: rows written, prompts sent, orders placed.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from a_domain.model.analysis.technical_settings import TechnicalSettings
from a_domain.model.chat.message import Message
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.types.enums import AiAnalysisFocus, MessageRole, WatchlistType
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, FixedOffsetMarketClock

PROMPT_TEMPLATES = {
    AiAnalysisFocus.FUNDAMENTAL: "fundamental analysis of {stock_id}\n{articles_text}",
    AiAnalysisFocus.MOMENTUM: "momentum analysis of {stock_id}\n{articles_text}",
}
PROMPT_HEADER = re.compile(r"^(fundamental|momentum) analysis of (\S+)")


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


class FakeMarketClock(FixedOffsetMarketClock):
    """Taiwan-time clock whose current time and market session are set by the test."""

    def __init__(self, now: datetime, market_open: bool) -> None:
        super().__init__(market_timezone=TAIWAN_TIMEZONE)
        self.current_time = now
        self.market_open = market_open

    def now(self) -> datetime:
        return self.current_time

    def is_market_open(self) -> bool:
        return self.market_open


class FakeStockProvider:
    """Like TaiwanStockProvider, every call returns the same shared Stock objects."""

    def __init__(self) -> None:
        self.stocks: dict[str, Stock] = {}

    async def get_all(self) -> list[Stock]:
        return list(self.stocks.values())

    async def get_by_id(self, stock_id: str) -> Stock | None:
        return self.stocks.get(stock_id)


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
    focus: AiAnalysisFocus
    prompt: str


class FakeAiProvider:
    """Answers each prompt with the score set for its stock; reads the stock from PROMPT_TEMPLATES' header."""

    def __init__(self, default_score: int = 90) -> None:
        self.default_score = default_score
        self.scores: dict[str, int] = {}
        self.failures: dict[str, Exception] = {}
        self.calls: list[AiCall] = []

    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        header = PROMPT_HEADER.match(messages[-1].content)
        assert header is not None, f"prompt does not start with a PROMPT_TEMPLATES header: {messages[-1].content!r}"
        focus, stock_id = AiAnalysisFocus(header.group(1)), header.group(2)
        self.calls.append(AiCall(stock_id=stock_id, focus=focus, prompt=messages[-1].content))

        if stock_id in self.failures:
            raise self.failures[stock_id]

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

    async def search(self, query: str, limit: int = 3) -> str:
        return ""

    async def save_decision(self, stock: Stock, signal: TradeSignal) -> None:
        self.decisions.append((stock.stock_id, signal))


class FakeSignalRepository:
    def __init__(self) -> None:
        self.saved: list[TradeSignal] = []

    async def save(self, signal: TradeSignal) -> None:
        self.saved.append(signal.model_copy())

    async def save_batch(self, signals: list[TradeSignal]) -> None:
        self.saved.extend(signal.model_copy() for signal in signals)

    async def get_by_stock_id(self, stock_id: str, start_date: datetime | None = None, limit: int = 10) -> list[TradeSignal]:
        matching = [
            signal
            for signal in self.saved
            if signal.stock_id == stock_id and (start_date is None or signal.generated_at >= start_date)
        ]
        return sorted(matching, key=lambda signal: signal.generated_at, reverse=True)[:limit]

    async def get_latest(self, limit: int = 50) -> list[TradeSignal]:
        return sorted(self.saved, key=lambda signal: signal.generated_at, reverse=True)[:limit]


class FakeWatchlistRepository:
    """Holds one row per (stock_id, type), like the watchlist table that WatchlistRepository writes."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, WatchlistType]] = []

    async def get_active(self) -> StockWatchlist:
        stocks_by_id: dict[str, Stock] = {}

        for stock_id, watchlist_type in self.rows:
            stocks_by_id.setdefault(stock_id, Stock(stock_id=stock_id)).watchlist_types.add(watchlist_type)

        return StockWatchlist(willing_stocks=list(stocks_by_id.values()))

    async def add(self, stocks: list[Stock], watchlist_type: WatchlistType) -> StockWatchlist:
        unique_stocks = {stock.stock_id: stock for stock in stocks}

        for stock in unique_stocks.values():
            stock.watchlist_types.add(watchlist_type)

            if (stock.stock_id, watchlist_type) not in self.rows:
                self.rows.append((stock.stock_id, watchlist_type))

        return StockWatchlist(willing_stocks=list(unique_stocks.values()))

    async def remove(self, stock_id: str) -> None:
        self.rows = [row for row in self.rows if row[0] != stock_id]


class RecordingExecutionProvider:
    """Broker that records each place_order call, rejects invalid orders like MockExecutionProvider, and fills the rest."""

    def __init__(self, cash: float = 1_000_000.0) -> None:
        self.cash = cash
        self.positions: list[Position] = []
        self.placed: list[Order] = []

    async def place_order(self, order: Order) -> Order:
        self.placed.append(order.model_copy())

        try:
            order.validate_submission()
        except ValueError as error:
            order.reject(str(error))
            return order

        assert order.limit_price is not None
        order.fill(order.limit_price)
        return order

    async def cancel_order(self, order_id: UUID) -> Order | None:
        return None

    async def get_positions(self) -> list[Position]:
        return [position.model_copy() for position in self.positions]

    async def get_cash_balance(self) -> float:
        return self.cash


class FakeTechnicalSettingsRepository:
    def __init__(self, settings: TechnicalSettings) -> None:
        self.settings = settings

    async def load(self) -> TechnicalSettings:
        return self.settings

    async def save(self, settings: TechnicalSettings) -> None:
        self.settings = settings
