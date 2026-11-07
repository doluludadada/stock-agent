"""The exchanges' daily reports as CachedPriceProvider reads them (IDailyHistorySource), scripted by the test, without the network."""

from collections.abc import Collection
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from itertools import pairwise
from typing import Any

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.types.enums import MarketType
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE


def close_of(session: date) -> datetime:
    return datetime.combine(session, time(13, 30), tzinfo=TAIWAN_TIMEZONE)


def session_bar(session: date, close: float, volume: int = 1000, change: float | None = None) -> Ohlcv:
    return Ohlcv(ts=close_of(session), open=close, high=close, low=close, close=close, volume=volume, change=change)


@dataclass
class FakeDailyHistory:
    """
    Serves each session's bars the test set (`sessions`) and each exchange's index over the sessions it set (`index`),
    each with its change from the session before it, as the reports give it. It also answers the realtime quotes the
    test set (`realtime`), as the broker would. Records every request in `asked`.
    """

    sessions: dict[date, dict[str, Ohlcv]] = field(default_factory=dict)
    index: dict[MarketType, list[date]] = field(default_factory=dict)
    realtime: dict[str, Ohlcv] = field(default_factory=dict)
    failure: Exception | None = None
    asked: list[str] = field(default_factory=list)

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        return {stock.stock_id: self.realtime[stock.stock_id] for stock in stocks if stock.stock_id in self.realtime}

    async def session_bars(self, session: date) -> dict[str, Ohlcv]:
        self.asked.append(f"quotes {session}")
        self.fail_if_told()
        return dict(self.sessions.get(session, {}))

    async def index_bars(self, market: MarketType, first: date, last: date) -> list[Ohlcv]:
        self.asked.append(f"index {market.value} {first} {last}")
        self.fail_if_told()
        days = self.index.get(market, [])
        bars = [session_bar(day, 100.0 + day.day) for day in days]
        changed = bars[:1] + [replace(later, change=later.close - earlier.close) for earlier, later in pairwise(bars)]
        return [bar for bar in changed if first <= bar.ts.date() <= last]

    async def get(self, market: MarketType, url: str) -> Any:
        raise AssertionError("the fake serves bars, never a report")

    def rows(self, answer: Any, fields: Collection[str]) -> list[dict[str, str]]:
        return []

    def quotes(self, answer: Any, market: MarketType, session: date) -> dict[str, Ohlcv]:
        return {}

    def change(self, sign: str, text: str, close: float) -> float | None:
        return None

    def index_month(self, prices: Any, volumes: Any, market: MarketType) -> list[Ohlcv]:
        return []

    def session_date(self, text: str) -> date | None:
        return None

    def fail_if_told(self) -> None:
        if self.failure is not None:
            raise self.failure
