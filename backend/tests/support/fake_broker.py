"""A broker's market data as CachedPriceProvider reads it (IBrokerQuoteProvider), scripted by the test, without the network."""

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from itertools import pairwise

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.types.enums import MarketType
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE


def close_of(session: date) -> datetime:
    return datetime.combine(session, time(13, 30), tzinfo=TAIWAN_TIMEZONE)


def session_bar(session: date, close: float, volume: int = 1000) -> Ohlcv:
    return Ohlcv(ts=close_of(session), open=close, high=close, low=close, close=close, volume=volume)


@dataclass
class FakeBrokerQuotes:
    """
    Serves each session's daily quotes the test set (`sessions`), each exchange's index over the sessions it set
    (`index`), with each one's change from the session before it in the answer as the real adapter computes it, and
    the snapshots' changes of the session they still show (`snapshot_changes`). Records every request in `asked`.
    """

    sessions: dict[date, dict[str, Ohlcv]] = field(default_factory=dict)
    index: dict[MarketType, list[date]] = field(default_factory=dict)
    snapshot_changes: dict[date, dict[str, float]] = field(default_factory=dict)
    realtime: dict[str, Ohlcv] = field(default_factory=dict)
    failure: Exception | None = None
    asked: list[str] = field(default_factory=list)

    async def connect(self) -> None:
        return None

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        return {stock.stock_id: self.realtime[stock.stock_id] for stock in stocks if stock.stock_id in self.realtime}

    async def snapshots(self, stock_ids: Collection[str]) -> list[object]:
        return []

    def quote_of(self, snapshot: object) -> Ohlcv | None:
        return None

    async def fetch_session_bars(self, session: date) -> dict[str, Ohlcv]:
        self.asked.append(f"quotes {session}")
        self.fail_if_told()
        return dict(self.sessions.get(session, {}))

    async def fetch_session_changes(self, session: date, stock_ids: Collection[str]) -> dict[str, float]:
        self.asked.append(f"changes {session}")
        changes = self.snapshot_changes.get(session, {})
        return {stock_id: changes[stock_id] for stock_id in stock_ids if stock_id in changes}

    async def fetch_index_bars(self, market: MarketType, first: date, last: date) -> list[Ohlcv]:
        self.asked.append(f"index {market.value} {first} {last}")
        self.fail_if_told()
        days = [day for day in self.index.get(market, []) if first <= day <= last]
        return self.daily_bars([session_bar(day, 100.0 + day.day) for day in days])

    def daily_bars(self, minutes: Sequence[Ohlcv]) -> list[Ohlcv]:
        bars = list(minutes[:1])
        bars += [replace(later, change=later.close - earlier.close) for earlier, later in pairwise(minutes)]
        return bars

    async def request[**Arguments, Answer](
        self, interval_seconds: float, call: Callable[Arguments, Answer], *args: Arguments.args, **kwargs: Arguments.kwargs
    ) -> Answer:
        return call(*args, **kwargs)

    def failure_of(self, error: Exception) -> str:
        return type(error).__name__

    def fail_if_told(self) -> None:
        if self.failure is not None:
            raise self.failure
