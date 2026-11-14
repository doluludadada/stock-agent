"""
`just backfill-history` brings what a ranking backtest reads back to a first day (Pipeline.backfill_history): the daily
history and the exchanges' ex-right references into the history cache, over the exchanges' reports scripted without the network,
and every market's monthly revenue from MOPS into the open-data archive. A failure keeps what was saved, and a rerun
asks only for what is still missing.
"""

from datetime import date, timedelta

import httpx
import pytest
from support.fake_daily_history import FakeDailyHistory, session_bar
from support.harness import build_harness, harness_config
from support.settings import shipped_config
from test_cached_price_provider import MONDAY, SESSIONS, at, cache_over
from test_revenue_history import revenue
from trading_stack import MovableClock

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.types.enums import Audience, MarketType
from b_application.use_cases.collect.daily_history_backfill import DailyHistoryBackfill
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.market.cached_price_provider import held_ex_right_references

pytestmark = pytest.mark.asyncio


def reported(sessions: list[date], close: float) -> dict[date, dict[str, Ohlcv]]:
    """2330's bar of each session as the reports give it, with its change."""
    return {day: {"2330": session_bar(day, close, change=0.0)} for day in sessions}


class TimingOut(FakeDailyHistory):
    """The reports, but the quotes of `stop` time out, as TWSE's site did overnight on 2026-11-12."""

    stop: date | None = None

    async def session_bars(self, session: date) -> dict[str, Ohlcv]:
        if session == self.stop:
            self.asked.append(f"quotes {session}")
            raise httpx.ReadTimeout("The read operation timed out")

        return await super().session_bars(session)


async def test_a_backfill_holds_every_session_from_its_first_day_and_a_rerun_after_a_timeout_asks_only_what_it_left(
    database: DatabaseConnector,
) -> None:
    clock = MovableClock(at(MONDAY, 16))
    reports = TimingOut(sessions=reported(SESSIONS, 100.0), index={market: SESSIONS for market in MarketType})
    reports.references = {("2330", SESSIONS[3]): 99.0}
    reports.stop = SESSIONS[10]

    held, missing, unread = await DailyHistoryBackfill(cache_over(reports, database, clock), clock, shipped_config()).execute(
        SESSIONS[0]
    ) or ([], [], [])

    assert (held, missing, unread) == (SESSIONS[11:], SESSIONS[:11], [])
    assert reports.references_asked == [(market, SESSIONS[0], MONDAY) for market in MarketType]

    reports.stop, reports.asked = None, []
    rerun = await DailyHistoryBackfill(cache_over(reports, database, clock), clock, shipped_config()).execute(SESSIONS[0])

    assert rerun == (SESSIONS, [], [])
    assert [question for question in reports.asked if question.startswith("quotes")] == [
        f"quotes {day}" for day in reversed(SESSIONS[:11])
    ]


async def test_a_backfill_goes_back_before_the_earliest_session_the_cache_holds(database: DatabaseConnector) -> None:
    clock = MovableClock(at(MONDAY, 16))
    reports = FakeDailyHistory(sessions=reported(SESSIONS, 100.0), index={market: SESSIONS for market in MarketType})
    await DailyHistoryBackfill(cache_over(reports, database, clock), clock, shipped_config()).execute(SESSIONS[-5])
    earlier = [SESSIONS[0] - timedelta(days=offset) for offset in (21, 20, 17)]
    reports.sessions |= reported(earlier, 90.0)
    reports.index = {market: [*earlier, *SESSIONS] for market in MarketType}

    held, missing, unread = await DailyHistoryBackfill(cache_over(reports, database, clock), clock, shipped_config()).execute(
        earlier[0]
    ) or ([], [], [])

    assert (held, missing, unread) == ([*earlier, *SESSIONS], [], [])


async def test_without_a_first_day_the_backfill_covers_the_stock_pages_longest_chart_as_the_timer_runs_it(
    database: DatabaseConnector,
) -> None:
    clock = MovableClock(at(MONDAY, 16))
    reports = FakeDailyHistory(sessions=reported(SESSIONS, 100.0), index={market: SESSIONS for market in MarketType})
    config = shipped_config()
    window_first = MONDAY - timedelta(days=config.analysis.history_days(config.market_data.history_backfill_bars))

    refreshed = await DailyHistoryBackfill(cache_over(reports, database, clock), clock, config).execute()

    assert refreshed is not None
    assert (refreshed[0], refreshed[1]) == (SESSIONS, [])
    assert reports.asked[0] == f"index {MarketType.TWSE.value} {window_first} {MONDAY}"
    assert await DailyHistoryBackfill(cache_over(reports, database, clock), clock, config).execute(window_first) == refreshed


async def test_a_backfill_names_the_ex_right_references_a_failed_request_left_unread_and_a_rerun_reads_them(
    database: DatabaseConnector,
) -> None:
    clock = MovableClock(at(MONDAY, 16))
    reports = FakeDailyHistory(sessions=reported(SESSIONS, 100.0), index={market: SESSIONS for market in MarketType})
    reports.tpex_references = {("6488", SESSIONS[3]): 99.0}
    reports.references_failing = {(MarketType.TPEX, SESSIONS[0]): httpx.ReadTimeout("The read operation timed out")}

    answer = await DailyHistoryBackfill(cache_over(reports, database, clock), clock, shipped_config()).execute(SESSIONS[0])

    assert answer == ([], SESSIONS, [(MarketType.TPEX, SESSIONS[0], MONDAY)])

    reports.references_failing = {}
    rerun_cache = cache_over(reports, database, clock)
    rerun = await DailyHistoryBackfill(rerun_cache, clock, shipped_config()).execute(SESSIONS[0])

    assert rerun == (SESSIONS, [], [])
    assert await held_ex_right_references(SESSIONS[0], MONDAY, database, clock) == {"6488": {at(SESSIONS[3], 13, 30): 99.0}}


async def test_the_operation_reads_the_revenue_of_every_month_from_the_first_day_and_a_public_site_backfills_nothing() -> None:
    harness = build_harness(now=at(date(2025, 2, 12), 18))
    filed = date(2025, 2, 12)
    harness.fundamentals.monthly_revenue_summaries = {
        (market, 2025, 1): [revenue(stock_id, market, 2025, 1, filed)]
        for market, stock_id in ((MarketType.TWSE, "2330"), (MarketType.TPEX, "6488"))
    }

    personal = await harness.runtime.signed_out.backfill_history(date(2025, 1, 1))
    public = await build_harness(
        config=harness_config().model_copy(update={"audience": Audience.PUBLIC})
    ).runtime.signed_out.backfill_history(date(2025, 1, 1))

    assert personal[:2] == (None, (2, 2))
    assert personal[2] is not None
    assert sorted(harness.archive.monthly_revenues) == [("2330", 2025, 1), ("6488", 2025, 1)]
    assert public == (None, None, None)


async def test_a_backfill_whose_reports_fail_names_each_exchanges_index_range_it_could_not_read(database: DatabaseConnector) -> None:
    clock = MovableClock(at(MONDAY, 16))
    reports = FakeDailyHistory(sessions=reported(SESSIONS, 100.0), index={market: SESSIONS for market in MarketType})
    reports.failure = httpx.ConnectError("TWSE refuses the address")

    answer = await DailyHistoryBackfill(cache_over(reports, database, clock), clock, shipped_config()).execute(SESSIONS[0])

    assert answer == ([], [], [(MarketType.TWSE, SESSIONS[0], MONDAY), (MarketType.TPEX, SESSIONS[0], MONDAY)])
