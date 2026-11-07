import asyncio
from dataclasses import replace
from datetime import date, datetime, time, timedelta

import pytest
from support.fake_daily_history import FakeDailyHistory, session_bar
from support.fakes import RecordingLogger
from support.settings import shipped_config
from trading_stack import MovableClock, SilentLogger

from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MarketIndex, MarketType
from b_application.config.market_data_config import MarketDataConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.daily_close_archive_dto import DailyCloseDTO
from c_infrastructure.database.repositories.daily_close_archive import SqlDailyCloseArchive
from c_infrastructure.market.cached_price_provider import CachedPriceProvider
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

pytestmark = pytest.mark.asyncio

MONDAY = date(2026, 11, 9)
TYPHOON = date(2026, 10, 23)
SESSIONS = [
    day for day in (date(2026, 10, 12) + timedelta(days=offset) for offset in range(29)) if day.weekday() < 5 and day != TYPHOON
]
"""The weekday sessions from 2026-10-12 to MONDAY but the typhoon day, which the exchanges closed."""
STOCKS = [Stock(stock_id="2330", market=MarketType.TWSE), Stock(stock_id="6488", market=MarketType.TPEX)]


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TAIWAN_TIMEZONE)


def reports_of(sessions: list[date], closes: dict[str, float]) -> FakeDailyHistory:
    return FakeDailyHistory(
        sessions={day: {stock_id: session_bar(day, close) for stock_id, close in closes.items()} for day in sessions},
        index={MarketType.TWSE: list(sessions), MarketType.TPEX: list(sessions)},
    )


def cache_over(
    reports: FakeDailyHistory, db: DatabaseConnector, clock: MovableClock, logger: ILoggingProvider | None = None
) -> CachedPriceProvider:
    archive = SqlDailyCloseArchive(db, clock, shipped_config().sources.exchange, 7, SilentLogger())
    return CachedPriceProvider(
        quotes=reports,
        source=reports,
        archive=archive,
        db=db,
        market_clock=clock,
        market_data=MarketDataConfig(),
        logger=logger or SilentLogger(),
        write_lock=asyncio.Lock(),
    )


def split_on_monday(change: float | None) -> FakeDailyHistory:
    """2330 at 100 until a 1:2 split on MONDAY, whose first session closes at 51, reported with `change`."""
    reports = reports_of(SESSIONS[:-1], {"2330": 100.0})
    reports.sessions[MONDAY] = {"2330": session_bar(MONDAY, 51.0, volume=4000, change=change)}
    reports.index = {MarketType.TWSE: SESSIONS, MarketType.TPEX: SESSIONS}
    return reports


@pytest.fixture
def db(database: DatabaseConnector) -> DatabaseConnector:
    """The cache's database on each backend: SQLite, and PostgreSQL when the suite has one."""
    return database


async def test_a_read_fills_the_cache_from_the_reports_and_a_second_read_asks_them_nothing(db: DatabaseConnector) -> None:
    clock = MovableClock(at(MONDAY, 16))
    reports = reports_of(SESSIONS, {"2330": 500.0, "6488": 300.0})
    cache = cache_over(reports, db, clock)

    first = await cache.fetch_history(STOCKS, *clock.history_window(30))
    asked_first = list(reports.asked)
    second = await cache.fetch_history(STOCKS, *clock.history_window(30))

    assert asked_first[:2] == ["index twse 2026-10-10 2026-11-09", "index tpex 2026-10-10 2026-11-09"]
    assert [question for question in asked_first if question.startswith("quotes")] == [f"quotes {day}" for day in reversed(SESSIONS)]
    assert reports.asked == asked_first
    assert first == second
    assert [clock.to_trading_date(bar.ts) for bar in first["2330"]] == SESSIONS
    assert {bar.close for bar in first["6488"]} == {300.0}


async def test_a_split_reported_with_its_change_from_the_converted_reference_adjusts_the_bars_before_it(db: DatabaseConnector) -> None:
    clock = MovableClock(at(MONDAY, 16))

    history = (await cache_over(split_on_monday(1.0), db, clock).fetch_history(STOCKS[:1], *clock.history_window(30)))["2330"]

    assert [(bar.close, bar.volume) for bar in history[-3:]] == [(50.0, 2000), (50.0, 2000), (51.0, 4000)]
    assert [bar.change for bar in history] == [None] * (len(SESSIONS) - 1) + [1.0]


async def test_a_session_the_reports_do_not_serve_yet_is_asked_again_only_after_the_retry_interval(db: DatabaseConnector) -> None:
    clock = MovableClock(at(MONDAY, 15, 30))
    reports = reports_of(SESSIONS[:-1], {"2330": 100.0})
    reports.index = {MarketType.TWSE: SESSIONS, MarketType.TPEX: SESSIONS}
    cache = cache_over(reports, db, clock)
    last_sessions = []

    for moment in (at(MONDAY, 15, 30), at(MONDAY, 17), at(MONDAY, 17, 31)):
        clock.current = moment

        if moment == at(MONDAY, 17, 31):
            reports.sessions[MONDAY] = {"2330": session_bar(MONDAY, 101.0, change=1.0)}

        history = await cache.fetch_history(STOCKS[:1], *clock.history_window(30))
        last_sessions.append((reports.asked.count(f"quotes {MONDAY}"), clock.to_trading_date(history["2330"][-1].ts)))

    assert last_sessions == [(1, SESSIONS[-2]), (1, SESSIONS[-2]), (2, MONDAY)]


async def test_reports_that_fail_leave_the_read_to_the_sessions_the_cache_holds(db: DatabaseConnector) -> None:
    clock = MovableClock(at(MONDAY, 16))
    reports = reports_of(SESSIONS, {"2330": 100.0})
    cache = cache_over(reports, db, clock)
    await cache.fetch_history(STOCKS[:1], *clock.history_window(30))

    clock.current = at(MONDAY + timedelta(days=1), 16)
    reports.failure = ConnectionError("TWSE refuses the address")
    history = await cache.fetch_history(STOCKS[:1], *clock.history_window(30))

    assert clock.to_trading_date(history["2330"][-1].ts) == MONDAY
    assert reports.asked[-1] == f"index twse {MONDAY} {MONDAY + timedelta(days=1)}"


async def test_an_index_history_asks_only_after_the_latest_session_it_holds_and_keeps_that_sessions_change(
    db: DatabaseConnector,
) -> None:
    clock = MovableClock(at(MONDAY, 16))
    tuesday = MONDAY + timedelta(days=1)
    reports = FakeDailyHistory(index={MarketType.TWSE: SESSIONS})
    cache = cache_over(reports, db, clock)
    first = await cache.fetch_index_history(MarketIndex.TAIEX, *clock.history_window(30))

    clock.current = at(tuesday, 16)
    reports.index[MarketType.TWSE] = [*SESSIONS, tuesday]
    second = await cache.fetch_index_history(MarketIndex.TAIEX, *clock.history_window(30))

    assert reports.asked == ["index twse 2026-10-10 2026-11-09", f"index twse {MONDAY} {tuesday}"]
    assert [clock.to_trading_date(bar.ts) for bar in first] == SESSIONS
    assert [(bar.close, bar.change) for bar in second[-2:]] == [(109.0, 3.0), (110.0, 1.0)]
    assert first[0].change is None


async def test_realtime_quotes_go_to_the_quote_provider_uncached(db: DatabaseConnector) -> None:
    quote = session_bar(MONDAY, 512.0)
    reports = FakeDailyHistory(realtime={"6488": quote})

    assert await cache_over(reports, db, MovableClock(at(MONDAY, 10))).fetch_realtime_bars(STOCKS) == {"6488": quote}
    assert reports.asked == []


async def test_the_timer_asks_again_once_for_sessions_saved_without_any_change_and_a_read_never_waits_for_them(
    db: DatabaseConnector,
) -> None:
    """Shioaji's daily quotes gave no change: the timer asks the reports for those sessions, and a read serves them as held."""
    clock = MovableClock(at(MONDAY, 16))
    await cache_over(FakeDailyHistory(), db, clock).save_bars(
        {"2330": [session_bar(day, 100.0) for day in SESSIONS[:-1]] + [session_bar(MONDAY, 51.0, volume=4000)]}
    )
    reports = split_on_monday(1.0)
    reports.sessions = {
        day: {stock: replace(bar, change=bar.change or 0.0) for stock, bar in bars.items()} for day, bars in reports.sessions.items()
    }
    cache = cache_over(reports, db, clock)
    quotes_asked = lambda: [question for question in reports.asked if question.startswith("quotes")]  # noqa: E731

    before = (await cache.fetch_history(STOCKS[:1], *clock.history_window(30)))["2330"]
    asked_by_the_read = quotes_asked()
    await cache.sync(*clock.history_window(30), reported=True)
    clock.current = at(MONDAY, 18, 1)
    await cache.sync(*clock.history_window(30), reported=True)
    after = (await cache.fetch_history(STOCKS[:1], *clock.history_window(30)))["2330"]

    assert asked_by_the_read == []
    assert quotes_asked() == [f"quotes {day}" for day in reversed(SESSIONS)]
    assert [(bar.close, bar.change) for bar in before[-2:]] == [(100.0, None), (51.0, None)]
    assert [(bar.close, bar.volume, bar.change) for bar in after[-2:]] == [(50.0, 2000, 0.0), (51.0, 4000, 1.0)]


async def test_a_bar_reported_without_a_change_takes_the_archives_official_change(db: DatabaseConnector) -> None:
    clock = MovableClock(at(MONDAY + timedelta(days=1), 9))
    async with db.get_session() as session:
        session.add(
            DailyCloseDTO(
                stock_id="2330",
                session_date=MONDAY,
                market="twse",
                open=51.0,
                high=51.0,
                low=51.0,
                close=51.0,
                volume=4000,
                change=1.0,
            )
        )
        await session.commit()

    history = (await cache_over(split_on_monday(None), db, clock).fetch_history(STOCKS[:1], *clock.history_window(30)))["2330"]

    assert [(bar.close, bar.volume, bar.change) for bar in history[-2:]] == [(50.0, 2000, None), (51.0, 4000, 1.0)]


async def test_a_read_warns_how_many_sessions_of_its_window_stay_without_a_change(db: DatabaseConnector) -> None:
    clock = MovableClock(at(MONDAY, 16))
    logger = RecordingLogger()
    reports = reports_of(SESSIONS, {"2330": 100.0, "6488": 300.0})
    reports.sessions[MONDAY] = {stock_id: replace(bar, change=0.0) for stock_id, bar in reports.sessions[MONDAY].items()}

    await cache_over(reports, db, clock, logger).fetch_history(STOCKS, *clock.history_window(30))

    warnings = [message for level, message in logger.records if level == "warning"]
    assert len(warnings) == 1 and f"{len(SESSIONS) - 2} sessions" in warnings[0]


async def test_after_a_failed_request_nothing_is_asked_again_before_the_retry_interval(db: DatabaseConnector) -> None:
    clock = MovableClock(at(MONDAY, 16))
    reports = reports_of(SESSIONS, {"2330": 100.0})
    reports.failure = ConnectionError("TWSE refuses the address")
    cache = cache_over(reports, db, clock)

    asked = []

    for moment in (at(MONDAY, 16), at(MONDAY, 16, 30), at(MONDAY, 17), at(MONDAY, 18, 1)):
        clock.current = moment
        await cache.fetch_history(STOCKS[:1], *clock.history_window(30))
        asked.append(reports.asked[len(sum(asked, [])) :])

    assert asked == [["index twse 2026-10-10 2026-11-09"], [], [], ["index twse 2026-10-10 2026-11-09"]]
