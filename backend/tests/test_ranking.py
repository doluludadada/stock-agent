"""
The monthly ranking as the owner reaches it: Pipeline.load_ranking and Pipeline.run_ranking_backtest over the harness's
held history and archived revenue, the Web API's two signed-in reads and their refusals, the ranking's history read
again only after a bar, a reference or a revenue changed, and the history cache's bars read a session at a time into the
listed history that placing them bar by bar gives.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from random import Random

import numpy as np
import pytest
from support.fake_daily_history import FakeDailyHistory
from support.harness import CliHarness, build_harness, harness_config
from support.settings import shipped_config
from support.web import serve
from test_cached_price_provider import cache_over
from test_ranking_rule import revenue
from trading_stack import MovableClock, SilentLogger, StockDirectory

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.daily_close_archive import OpenDataDownload
from a_domain.rules.trading.ranking import ListedHistory, ListedHistoryRule, RankingHistoryRule
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.daily_close_archive import SqlDailyCloseArchive
from c_infrastructure.market.cached_price_provider import held_ex_right_references, save_bars, save_references
from c_infrastructure.market.daily_bar_matrix_provider import DailyBarMatrixProvider
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

pytestmark = pytest.mark.asyncio

SESSIONS = [date(2026, 3, day) for day in (11, 12, 13, 16, 17)]
"""The ranking decides at the close of March 13, its first session on the 13th or later, and reads February's revenue."""


def bars(closes: list[float]) -> list[Ohlcv]:
    return [
        Ohlcv(
            ts=datetime.combine(day, time(13, 30), TAIWAN_TIMEZONE),
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=10**6,
        )
        for day, close in zip(SESSIONS, closes, strict=True)
    ]


def market() -> CliHarness:
    """
    Three stocks at their highs over the last three sessions, so revenue orders them: 2330 doubled its revenue in
    February, 2317 held it, 1101 halved it. The ranking holds two and reads three sessions for the high.
    """
    config = harness_config()
    windows = {"top": 2, "high_sessions": 3, "traded_value_sessions": 2, "revenue_short_months": 1, "revenue_long_months": 2}
    harness = build_harness(config=config.model_copy(update={"ranking": config.ranking.model_copy(update=windows)}))

    for stock_id, closes in {"2330": [100, 101, 102, 103, 104], "2317": [50, 51, 52, 53, 54], "1101": [30, 31, 32, 33, 34]}.items():
        harness.list_stock(stock_id, bars(closes))

    for stock_id, january, february in (("2330", 100.0, 200.0), ("2317", 100.0, 100.0), ("1101", 100.0, 50.0)):
        harness.archive.monthly_revenues[(stock_id, 2026, 1)] = revenue(stock_id, 2026, 1, january)
        harness.archive.monthly_revenues[(stock_id, 2026, 2)] = revenue(stock_id, 2026, 2, february)

    return harness


async def test_the_latest_ranking_is_the_last_decision_sessions_best_scores_named_by_the_listing() -> None:
    ranking = await market().runtime.signed_out.load_ranking()

    assert (ranking.decided_on, ranking.revenue_month, ranking.universe, ranking.scored) == (SESSIONS[2], date(2026, 2, 1), 3, 3)
    assert [(stock.stock_id, stock.stock_name) for stock in ranking.stocks] == [("2330", "Stock 2330"), ("2317", "Stock 2317")]


async def test_the_web_api_answers_the_latest_ranking_and_its_backtest_to_a_signed_in_user() -> None:
    async with serve(market()) as client:
        latest = await client.get("/v1/rankings/latest")
        backtest = await client.get("/v1/rankings/backtest", params={"first": "2026-03-01", "last": "2026-03-17"})

    assert latest.status_code == 200, latest.text
    assert [stock["stock_id"] for stock in latest.json()["stocks"]] == ["2330", "2317"]
    assert backtest.status_code == 200, backtest.text
    answer = backtest.json()
    assert list(answer["holdings"]) == ["2026-03-16"]
    assert answer["holdings"]["2026-03-16"] == ["2330", "2317"]
    assert list(answer["equity_curve"]) == ["2026-03-13", "2026-03-16", "2026-03-17"]
    assert (answer["benchmark_curve"], answer["benchmark_total_return"]) == ({}, None)
    assert answer["total_return"] == pytest.approx(answer["equity_curve"]["2026-03-17"] - 1)
    assert {"annual_return", "max_drawdown", "yearly_returns", "costs", "rankings"} <= answer.keys()


async def test_the_web_api_refuses_a_ranking_without_history_a_period_without_a_decision_and_a_signed_out_user() -> None:
    async with serve(build_harness()) as client:
        empty = await client.get("/v1/rankings/latest")

    async with serve(market()) as client:
        outside = await client.get("/v1/rankings/backtest", params={"first": "2026-03-16", "last": "2026-03-17"})

    async with serve(market(), authorized=False) as client:
        anonymous = [
            (await client.get(path)).status_code
            for path in ("/v1/rankings/latest", "/v1/rankings/backtest?first=2026-03-01&last=2026-03-17")
        ]

    assert (empty.status_code, empty.json()["code"]) == (422, "ranking_unavailable")
    assert (outside.status_code, outside.json()["code"]) == (422, "backtest_period_unavailable")
    assert anonymous == [401, 401]


async def test_the_ranking_history_is_read_once_and_again_only_after_a_bar_a_reference_or_a_revenue_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = market()
    reads: list[int] = []
    listed_history = harness.prices.listed_history

    async def counted() -> ListedHistory | None:
        reads.append(len(reads))
        return await listed_history()

    async def read_after(change: Callable[[], object]) -> int:
        change()
        await harness.runtime.signed_out.load_ranking()
        await harness.runtime.signed_out.run_ranking_backtest(SESSIONS[0], SESSIONS[-1])
        return len(reads)

    monkeypatch.setattr(harness.prices, "listed_history", counted)
    wednesday = Ohlcv(ts=datetime(2026, 3, 18, 13, 30, tzinfo=TAIWAN_TIMEZONE), open=105, high=106, low=104, close=105, volume=10**6)
    march = revenue("2330", 2026, 3, 300.0)

    assert await read_after(lambda: None) == 1
    assert await read_after(lambda: harness.prices.history["2330"].append(wednesday)) == 2
    assert await read_after(lambda: harness.prices.references.update({"2317": {bars([0] * 5)[-1].ts: 53.5}})) == 3
    assert await read_after(lambda: harness.archive.monthly_revenues.update({("2330", 2026, 3): march})) == 4
    assert await read_after(lambda: None) == 4


async def test_a_ranking_history_whose_build_fails_is_not_kept_and_the_next_call_builds_it(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = market()
    revenue_history = harness.archive.revenue_history

    async def unreachable(first: date, last: date) -> dict[tuple[str, int, int], float | None]:
        raise ConnectionError("the database went away")

    monkeypatch.setattr(harness.archive, "revenue_history", unreachable)
    with pytest.raises(ConnectionError):
        await harness.runtime.signed_out.load_ranking()

    monkeypatch.setattr(harness.archive, "revenue_history", revenue_history)
    ranking = await harness.runtime.signed_out.load_ranking()

    assert [stock.stock_id for stock in ranking.stocks] == ["2330", "2317"]


def synthetic_market() -> tuple[dict[str, list[Ohlcv]], dict[tuple[str, date], float]]:
    """
    Twelve stocks over 200 weekdays: a stock misses about one session in six, a bar in five gives no change, and a
    session in twenty has an ex-right reference, some of them of sessions the stock has no bar of. The index has a bar
    of every weekday and of the Saturday after them, which no stock traded.
    """
    chance = Random(7)
    days = [day for day in (date(2025, 6, 2) + timedelta(days=offset) for offset in range(280)) if day.weekday() < 5]
    stamps = [datetime.combine(day, time(13, 30), TAIWAN_TIMEZONE) for day in days]
    saturday = datetime.combine(days[-1] + timedelta(days=1), time(13, 30), TAIWAN_TIMEZONE)
    history = {"^twse": [Ohlcv(ts=stamp, open=1, high=1, low=1, close=1, volume=1) for stamp in [*stamps, saturday]]}

    for stock_id in ("0050", "00679B", *(f"{code}" for code in range(1101, 1111))):
        closes = [round(chance.uniform(5, 900), 2) for _ in stamps]
        history[stock_id] = [
            Ohlcv(
                ts=stamp,
                open=round(close * 0.99, 2),
                high=round(close * 1.02, 2),
                low=round(close * 0.97, 2),
                close=close,
                volume=chance.randrange(0, 10**9),
                change=None if chance.random() < 0.2 else round(chance.uniform(-9, 9), 2),
            )
            for stamp, close in zip(stamps, closes, strict=True)
            if chance.random() > 1 / 6
        ]

    references = {
        (stock_id, day): round(chance.uniform(5, 900), 2) for stock_id in history for day in days if chance.random() < 1 / 20
    }
    return history, references


async def test_the_history_cache_reads_its_bars_a_session_at_a_time_into_the_listed_history_that_placing_them_bar_by_bar_gives(
    database: DatabaseConnector,
) -> None:
    clock = MovableClock(datetime(2026, 3, 17, 16, 0, tzinfo=TAIWAN_TIMEZONE))
    cache = cache_over(FakeDailyHistory(), database, clock)
    history, references = synthetic_market()
    empty = await cache.listed_history()
    await save_bars(history, database)
    await save_references(references, database)
    stocks = {stock_id: bars for stock_id, bars in history.items() if stock_id != "^twse"}
    plain = ListedHistoryRule().apply(
        stocks, await held_ex_right_references(date.min, date.max, database, clock), clock.to_trading_date
    )

    fast = await cache.listed_history()

    assert empty is None and fast is not None
    assert (fast.bars.stock_ids, fast.bars.sessions) == (plain.bars.stock_ids, plain.bars.sessions)
    assert all(np.array_equal(fast.bars.fields[field], values, equal_nan=True) for field, values in plain.bars.fields.items())
    assert np.array_equal(fast.change, plain.change, equal_nan=True)
    assert np.array_equal(fast.ex_right_reference, plain.ex_right_reference, equal_nan=True)
    assert plain.bars.close.shape == (12, 200)
    assert (np.isfinite(plain.bars.close).sum(), np.isfinite(plain.change).sum(), np.isfinite(plain.ex_right_reference).sum()) == (
        sum(map(len, stocks.values())),
        sum(bar.change is not None for bars in stocks.values() for bar in bars),
        sum((stock_id, clock.to_trading_date(bar.ts)) in references for stock_id, bars in stocks.items() for bar in bars),
    )
    assert 0 < np.isfinite(plain.ex_right_reference).sum() < len(references)


async def test_the_listed_fingerprint_changes_with_every_bar_or_reference_saved_filled_or_replaced_and_with_nothing_else(
    database: DatabaseConnector,
) -> None:
    clock = MovableClock(datetime(2026, 3, 17, 16, 0, tzinfo=TAIWAN_TIMEZONE))
    cache = cache_over(FakeDailyHistory(), database, clock)
    held = bars([100, 101, 102, 103, 104])
    seen = [await cache.listed_fingerprint()]

    async def fingerprint_after(saved: dict[str, list[Ohlcv]], references: dict[tuple[str, date], float]) -> tuple[object, ...]:
        await save_bars(saved, database)
        await save_references(references, database)
        return await cache.listed_fingerprint()

    changes: list[tuple[dict[str, list[Ohlcv]], dict[tuple[str, date], float]]] = [
        ({"2330": held[:1] + held[2:]}, {}),
        ({"2330": held[1:2]}, {}),
        ({"2317": held[1:2]}, {}),
        ({"2330": [replace(held[2], change=1.0)]}, {}),
        ({"2330": [replace(held[3], close=103.5)]}, {}),
        ({}, {("2330", SESSIONS[2]): 101.0}),
        ({}, {("2330", SESSIONS[2]): 101.5}),
    ]

    spans = []

    for saved, references in changes:
        seen.append(await fingerprint_after(saved, references))
        spans.append(await cache.held_span())
        assert seen[-1] not in seen[:-1], (saved, references)

    assert set(spans) == {(SESSIONS[0], SESSIONS[-1])}
    assert await fingerprint_after({"^twse": bars([20000] * 5), "2330": []}, {}) == seen[-1]


async def test_the_ranking_history_is_never_older_than_the_bars_the_references_and_the_revenue_the_database_holds(
    database: DatabaseConnector,
) -> None:
    clock = MovableClock(datetime(2026, 3, 17, 16, 0, tzinfo=TAIWAN_TIMEZONE))
    cache = cache_over(FakeDailyHistory(), database, clock)
    archive = SqlDailyCloseArchive(database, clock, shipped_config().sources.exchange, 7, SilentLogger())
    provider = DailyBarMatrixProvider(StockDirectory(), cache, archive, clock, RankingHistoryRule(daily_limit=0.105), SilentLogger())
    await save_bars({"2330": bars([100, 100, 90, 90, 90])}, database)
    first = await provider.load_ranking_history()
    again = await provider.load_ranking_history()
    await save_references({("2330", SESSIONS[2]): 90.0}, database)
    referenced = await provider.load_ranking_history()
    held = OpenDataDownload(
        stocks=[],
        indexes={},
        material_information=[],
        quarter_eps={},
        valuation_ratios=[],
        financial_reports=[],
        monthly_revenues=[],
        exchange_news=[],
    )
    await archive.save(replace(held, monthly_revenues=[revenue("2330", 2026, 2, 200.0)]))
    with_revenue = await provider.load_ranking_history()
    await archive.save(replace(held, monthly_revenues=[revenue("2330", 2026, 2, 250.0)]))
    revised = await provider.load_ranking_history()

    assert first is not None and referenced is not None and with_revenue is not None and revised is not None
    assert again is first
    assert await cache.held_span() == (SESSIONS[0], SESSIONS[-1])
    assert (first.returns[0, 2], referenced.returns[0, 2]) == (pytest.approx(-0.1), 0.0)
    assert (first.months, with_revenue.months) == ((), (date(2026, 2, 1),))
    assert (with_revenue.revenue.tolist(), revised.revenue.tolist()) == ([[200.0]], [[250.0]])
    assert await provider.load_ranking_history() is revised
