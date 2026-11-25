"""
The Web API's daily data timer (collect_daily_data): when its rounds start by the market clock, and the monthly ranking
its round loads right after the daily history, so the next viewer's ranking reads the kept history.
"""

import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest
from support.harness import CliHarness, build_harness, harness_config, open_harness_switch
from test_ranking import market

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.rules.trading.ranking import ListedHistory
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE
from d_presentation.dependencies import compose_runtime
from d_presentation.live_runtime import collect_daily_data

pytestmark = pytest.mark.asyncio


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """March 2026 in Taipei: the 18th is a Wednesday, the 20th a Friday, the 23rd a Monday."""
    return datetime(2026, 3, day, hour, minute, tzinfo=TAIWAN_TIMEZONE)


class Stopped(Exception):
    """Ends the timer at its wait after the last round a test runs."""


async def round_starts(harness: CliHarness, rounds: int, lasting: timedelta = timedelta(0)) -> list[datetime]:
    """
    When the timer's first `rounds` rounds ask the OpenAPI for its closes, on the harness's clock, which each round
    moves on by `lasting` and each wait of the timer by as long as it waits.
    """
    asked: list[datetime] = []
    latest_closes = harness.stocks.get_latest_closes

    async def counted() -> dict[str, Ohlcv]:
        asked.append(harness.clock.now())
        harness.clock.current_time += lasting
        return await latest_closes()

    async def wait(seconds: float) -> None:
        if len(asked) == rounds:
            raise Stopped
        harness.clock.current_time += timedelta(seconds=max(seconds, 0))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(harness.stocks, "get_latest_closes", counted)
        patch.setattr(asyncio, "sleep", wait)

        async with open_harness_switch(harness) as switch:
            with pytest.raises(Stopped):
                await collect_daily_data(switch)

    return asked


@pytest.mark.parametrize(
    ("start", "hours", "lasting", "starts"),
    [
        pytest.param(at(18, 13, 46), 3, 0, [at(18, 13, 46), at(18, 15), at(18, 18)], id="before the settle"),
        pytest.param(
            at(18, 16),
            3,
            0,
            [at(18, 16), at(18, 19), at(18, 22), at(19, 1), at(19, 4), at(19, 7), at(19, 10), at(19, 13), at(19, 15), at(19, 18)],
            id="the next day's settle before the interval",
        ),
        pytest.param(at(20, 16), 24, 0, [at(20, 16), at(21, 16), at(22, 16), at(23, 15), at(24, 15)], id="over a weekend"),
        pytest.param(at(18, 14, 58), 3, 5, [at(18, 14, 58), at(18, 15, 3), at(18, 18, 8)], id="a round past the settle"),
    ],
)
async def test_a_round_starts_at_the_interval_or_at_the_next_weekdays_settle_whichever_comes_first(
    start: datetime, hours: float, lasting: int, starts: list[datetime]
) -> None:
    config = harness_config()
    harness = build_harness(
        now=start, config=config.model_copy(update={"api": config.api.model_copy(update={"archive_interval_hours": hours})})
    )

    assert harness.config.market_hours.settled.hour == 15
    assert await round_starts(harness, len(starts), timedelta(minutes=lasting)) == starts


async def test_a_round_ranks_the_session_the_daily_history_saved_and_the_next_viewer_reads_that_kept_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = market()
    harness.clock.current_time = at(18, 15)
    # The site's own writing ranks a new session too (SystemWritingStocks); off, only the round's ranking step can.
    harness.dependencies = replace(harness.dependencies, system_ai_provider=None)
    harness.runtime = compose_runtime(harness.config, harness.logger, harness.clock, harness.dependencies)
    assert harness.runtime.system_writer is None
    wednesday = Ohlcv(ts=at(18, 13, 30), open=105, high=106, low=104, close=105, volume=10**6)
    builds: list[int] = []
    listed_history = harness.prices.listed_history

    async def built() -> ListedHistory | None:
        builds.append(len(builds))
        return await listed_history()

    async def saves_wednesday(first: date | None = None) -> None:
        harness.prices.history["2330"].append(wednesday)

    monkeypatch.setattr(harness.prices, "listed_history", built)
    monkeypatch.setattr(harness.runtime.signed_out.daily_history_backfill, "execute", saves_wednesday)

    await round_starts(harness, 1)
    assert len(builds) == 1, "the round itself built the ranking's history"

    ranking = await harness.pipeline.load_ranking()

    assert [stock.stock_id for stock in ranking.stocks] == ["2330", "2317"]
    assert len(builds) == 1, "the viewer's ranking read the history the round built, Wednesday's bar included"
