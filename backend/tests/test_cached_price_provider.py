import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import pytest
import pytest_asyncio
from trading_stack import MONDAY_10_00, MovableClock, QuoteFeed, SilentLogger, bar

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.types.enums import TradingPhase
from b_application.config.app_config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.market.cached_price_provider import CachedPriceProvider

pytestmark = pytest.mark.asyncio


class CountingYahoo:
    """Serves the closed sessions plus, while a session runs, its in-progress bar at the latest price, as Yahoo does."""

    def __init__(self, clock: MovableClock) -> None:
        self.clock = clock
        self.calls = 0

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        self.calls += 1
        last_close = datetime.combine(self.clock.last_closed_session(), time(13, 30), tzinfo=self.clock.current.tzinfo)
        bars = [bar(last_close - timedelta(days=day), 100) for day in range(3, -1, -1)]

        if self.clock.trading_phase() in {TradingPhase.CONTINUOUS, TradingPhase.CLOSING_AUCTION}:
            bars.append(bar(self.clock.current.replace(hour=13, minute=30), 110))

        return {stock.stock_id: [one.model_copy() for one in bars] for stock in stocks}


@dataclass
class ScriptedYahoo:
    """Serves the daily bars the test sets, as Yahoo would after dropping rows without a close, and records who was asked for."""

    daily: dict[str, list[Ohlcv]] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        self.asked.extend(stock.stock_id for stock in stocks)
        return {
            stock.stock_id: [one.model_copy() for one in self.daily[stock.stock_id]]
            for stock in stocks
            if stock.stock_id in self.daily
        }


def session_close(day: date, close: float) -> Ohlcv:
    return bar(datetime.combine(day, time(13, 30), tzinfo=MONDAY_10_00.tzinfo), close)


THURSDAY, FRIDAY = date(2026, 10, 22), date(2026, 10, 23)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=MONDAY_10_00.tzinfo)


def cache_over(yahoo: ScriptedYahoo, db: DatabaseConnector, clock: MovableClock) -> CachedPriceProvider:
    return CachedPriceProvider(history_provider=yahoo, quote_provider=QuoteFeed(), db=db, logger=SilentLogger(), market_clock=clock)


async def last_bars(cache: CachedPriceProvider, clock: MovableClock, *stock_ids: str) -> dict[str, tuple[str, float]]:
    history = await cache.fetch_history([Stock(stock_id=stock_id) for stock_id in stock_ids], *clock.history_window(30))
    return {stock_id: (clock.to_trading_date(bars[-1].ts).isoformat(), bars[-1].close) for stock_id, bars in history.items()}


@pytest_asyncio.fixture
async def db(tmp_path):
    connector = DatabaseConnector(config=AppConfig(project_root=tmp_path), logger=SilentLogger())
    await connector.init_db()
    yield connector
    await connector.close()


async def test_history_holds_settled_sessions_and_is_refetched_when_a_newer_one_settles(db: DatabaseConnector) -> None:
    clock = MovableClock(MONDAY_10_00 + timedelta(days=1))
    yahoo = CountingYahoo(clock)
    cache = CachedPriceProvider(history_provider=yahoo, quote_provider=QuoteFeed(), db=db, logger=SilentLogger(), market_clock=clock)
    seen = []

    for moment in ["Tue 10:00", "Tue 11:00", "Tue 14:00", "Tue 15:00", "Sat 10:00", "Sat 12:00"]:
        day, hour = moment.split()
        clock.current = (MONDAY_10_00 + timedelta(days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].index(day))).replace(
            hour=int(hour[:2])
        )
        start, end = clock.history_window(30)
        bars = (await cache.fetch_history([Stock(stock_id="2330")], start, end))["2330"]
        seen.append((moment, yahoo.calls, clock.to_trading_date(bars[-1].ts).isoformat(), bars[-1].close))

    assert seen == [
        ("Tue 10:00", 1, "2026-10-19", 100),
        ("Tue 11:00", 1, "2026-10-19", 100),
        ("Tue 14:00", 1, "2026-10-19", 100),
        ("Tue 15:00", 2, "2026-10-20", 100),
        ("Sat 10:00", 3, "2026-10-23", 100),
        ("Sat 12:00", 3, "2026-10-23", 100),
    ]


async def test_realtime_quotes_come_from_the_quote_source_and_are_never_cached(db: DatabaseConnector) -> None:
    clock = MovableClock(MONDAY_10_00)
    quotes = QuoteFeed(realtime={"2330": bar(MONDAY_10_00, 101)})
    cache = CachedPriceProvider(
        history_provider=CountingYahoo(clock), quote_provider=quotes, db=db, logger=SilentLogger(), market_clock=clock
    )

    first = await cache.fetch_realtime_bars([Stock(stock_id="2330")])
    quotes.realtime["2330"] = bar(MONDAY_10_00 + timedelta(minutes=1), 102)
    second = await cache.fetch_realtime_bars([Stock(stock_id="2330")])

    assert (first["2330"].close, second["2330"].close) == (101, 102)


async def test_a_refetched_session_replaces_its_bar_and_stays_one_row(db: DatabaseConnector, tmp_path) -> None:
    clock = MovableClock(MONDAY_10_00 + timedelta(days=1))
    monday, tuesday = (
        datetime.combine(day, time(13, 30), tzinfo=clock.current.tzinfo) for day in (date(2026, 10, 19), date(2026, 10, 20))
    )
    yahoo = ScriptedYahoo(daily={"2330": [bar(monday, 100)]})
    cache = cache_over(yahoo, db, clock)

    await cache.fetch_history([Stock(stock_id="2330")], *clock.history_window(30))
    yahoo.daily["2330"] = [bar(monday, 101), bar(tuesday, 102)]
    clock.current = clock.current.replace(hour=15)
    history = await cache.fetch_history([Stock(stock_id="2330")], *clock.history_window(30))

    assert [(one.ts, one.close) for one in history["2330"]] == [(monday, 101), (tuesday, 102)]
    with sqlite3.connect(tmp_path / "stock_agent.db") as connection:
        rows = connection.execute("SELECT ts, close FROM ohlcv_data ORDER BY ts").fetchall()
    assert rows == [("2026-10-19 05:30:00.000000", 101.0), ("2026-10-20 05:30:00.000000", 102.0)]


async def test_a_close_fetched_before_yahoo_settles_it_is_not_cached_as_final(db: DatabaseConnector) -> None:
    clock = MovableClock(at(FRIDAY, 13, 35))
    yahoo = ScriptedYahoo(daily={"2330": [session_close(THURSDAY, 100), session_close(FRIDAY, 105)]})
    cache = cache_over(yahoo, db, clock)

    seen = [await last_bars(cache, clock, "2330")]
    yahoo.daily["2330"][-1] = session_close(FRIDAY, 110)
    clock.current = at(FRIDAY, 20)
    seen.append(await last_bars(cache, clock, "2330"))
    clock.current = at(FRIDAY + timedelta(days=1), 10)
    seen.append(await last_bars(cache, clock, "2330"))

    assert seen == [{"2330": ("2026-10-22", 100)}, {"2330": ("2026-10-23", 110)}, {"2330": ("2026-10-23", 110)}]
    assert yahoo.asked == ["2330", "2330"]


async def test_a_session_yahoo_has_not_published_is_asked_for_again_only_every_two_hours(db: DatabaseConnector) -> None:
    clock = MovableClock(at(FRIDAY, 16))
    yahoo = ScriptedYahoo(daily={"2330": [session_close(THURSDAY, 100)]})
    asked = []

    for moment, cache in [
        (at(FRIDAY, 16), cache_over(yahoo, db, clock)),
        (at(FRIDAY, 17), cache_over(yahoo, db, clock)),
        (at(FRIDAY, 17, 59), cache_over(yahoo, db, clock)),
        (at(FRIDAY, 18), cache_over(yahoo, db, clock)),
    ]:
        clock.current = moment
        yahoo.asked.clear()
        served = await last_bars(cache, clock, "2330", "9999")
        asked.append((moment.strftime("%H:%M"), list(yahoo.asked), served))
        yahoo.daily["2330"] = [session_close(THURSDAY, 100), session_close(FRIDAY, 110)]

    assert asked == [
        ("16:00", ["2330", "9999"], {"2330": ("2026-10-22", 100)}),
        ("17:00", [], {"2330": ("2026-10-22", 100)}),
        ("17:59", [], {"2330": ("2026-10-22", 100)}),
        ("18:00", ["2330", "9999"], {"2330": ("2026-10-23", 110)}),
    ]
