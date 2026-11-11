"""
A backtest through the Pipeline and the Web API over fake ports: it replays the user's active strategy on the held
daily history, saves the result for that user alone, and touches no account, journal, watchlist, AI or broker.
"""

from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from support.harness import ADMINISTRATOR_PASSWORD, HISTORY_LAST_SESSION, MEMBER, MEMBER_PASSWORD, CliHarness, build_harness
from support.web import app_of, client_at, serve, sign_in, write

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.trading.account import Account
from a_domain.model.trading.backtest import Backtest, BacktestInputs, BacktestTrade
from a_domain.types.enums import MarketIndex, SignalSource
from a_domain.types.errors import BacktestPeriodUnavailable
from a_domain.types.ids import UserId
from b_application.config.market_data_config import MarketHoursConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.backtest_repository import SqlBacktestRepository
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

pytestmark = pytest.mark.asyncio

HELD_DAYS = 160
FIRST_HELD = HISTORY_LAST_SESSION - timedelta(days=HELD_DAYS - 1)
FIRST = FIRST_HELD + timedelta(days=120)
"""The harness strategy needs 5 bars, so a run reads analysis.lookback_days, 120 days, of history before its day."""


def bars(closes: list[float], last_session: date = HISTORY_LAST_SESSION) -> list[Ohlcv]:
    """One bar per calendar day up to last_session, opening at the close before it and trading around both."""
    close_time = MarketHoursConfig().close
    opens = [closes[0], *closes[:-1]]

    return [
        Ohlcv(
            ts=datetime.combine(last_session - timedelta(days=len(closes) - 1 - day), close_time, TAIWAN_TIMEZONE),
            open=open_,
            high=max(open_, close) + 0.5,
            low=min(open_, close) - 0.5,
            close=close,
            volume=1000,
        )
        for day, (open_, close) in enumerate(zip(opens, closes, strict=True))
    ]


def market() -> CliHarness:
    """
    2330 climbs a dollar a day, so it is above its 5-day average on every session and scores 90. 2317 climbs to the
    first day a backtest may cover, then loses 4% a day: bought nowhere, since it is below its average from then on.
    2603 climbs until five sessions into the period and then falls 6% a day, through its stop-loss.
    """
    harness = build_harness()
    climbing = [100.0 + day for day in range(HELD_DAYS)]
    peak = 125
    harness.list_stock("2330", bars(climbing))
    harness.list_stock("2317", bars([*climbing[:120], *(climbing[119] * 0.96**day for day in range(1, 41))]))
    harness.list_stock("2603", bars([*climbing[:peak], *(climbing[peak - 1] * 0.94**day for day in range(1, HELD_DAYS - peak + 1))]))
    harness.prices.index_history[MarketIndex.TAIEX] = bars([20_000.0 + 10 * day for day in range(40)])

    return harness


def inputs(first: date = FIRST, last: date = HISTORY_LAST_SESSION, **changes: Any) -> BacktestInputs:
    return replace(BacktestInputs(first=first, last=last, initial_cash=1_000_000, buy_score=80, sell_score=30), **changes)


async def test_a_backtest_replays_the_active_strategy_on_the_held_history_and_saves_it() -> None:
    harness = market()

    backtest = await harness.pipeline.run_backtest(inputs())

    assert (backtest.strategy_id, backtest.strategy_name, backtest.inputs) == ("trend", "Trend", inputs())
    assert (backtest.stop_loss_pct, backtest.risk_per_trade_pct) == (0.10, 0.02)
    assert (backtest.first_session, backtest.last_session, len(backtest.equity_curve)) == (FIRST, HISTORY_LAST_SESSION, 40)
    assert backtest.equity_curve[FIRST] == Account(cash=1_000_000)
    assert [(trade.stock_id, trade.stock_name, trade.exit_source) for trade in backtest.trades] == [
        ("2603", "Stock 2603", SignalSource.STOP_LOSS),
        ("2330", "Stock 2330", None),
    ]
    stopped, kept = backtest.trades
    assert (stopped.bought_on, stopped.pnl < 0, kept.bought_on, kept.pnl > 0) == (
        FIRST + timedelta(days=1),
        True,
        FIRST + timedelta(days=1),
        True,
    )
    last = backtest.equity_curve[HISTORY_LAST_SESSION]
    assert last.cash + sum(position.cost_basis for position in last.positions) == pytest.approx(1_000_000 + stopped.pnl)
    assert (backtest.final_equity, backtest.total_return_pct) == (last.equity, last.equity / 1_000_000 - 1)
    assert last.unrealized_pnl == kept.pnl < last.equity - 1_000_000 - stopped.pnl
    assert (backtest.trade_count, backtest.winning_trades, backtest.tax > 0) == (2, 1, True)
    assert backtest.benchmark_return_pct == pytest.approx(390 / 20_000)
    assert await harness.pipeline.load_backtests() == [backtest]
    assert await harness.pipeline.load_backtest(backtest.backtest_id) == backtest


async def test_a_backtest_touches_no_account_journal_watchlist_ai_or_broker() -> None:
    harness = market()
    harness.hold("2330", quantity=1000, average_cost=100.0)

    await harness.pipeline.run_backtest(inputs())

    assert (harness.broker.placed, harness.journal.runs, harness.journal.signals, harness.watchlist.rows, harness.ai.calls) == (
        [],
        {},
        [],
        [],
        [],
    )
    assert [(position.stock_id, position.quantity) for position in (await harness.broker.get_account()).positions] == [("2330", 1000)]
    assert harness.prices.realtime_requests == []


async def test_the_scores_of_a_backtest_are_its_own_and_the_other_settings_are_the_live_ones() -> None:
    """Every passing session scores 90: at a buy score of 91 nothing is ever bought."""
    harness = market()

    never = await harness.pipeline.run_backtest(inputs(buy_score=91))

    assert (never.trades, never.final_equity, never.total_return_pct, never.max_drawdown_pct) == ([], 1_000_000, 0, 0)
    assert never.average_held_sessions is None


async def test_the_options_are_the_longest_backtest_the_history_allows_at_the_live_settings() -> None:
    harness = market()

    strategy, longest = await harness.pipeline.load_backtest_options()

    assert strategy.strategy_id == "trend"
    assert longest == inputs()
    assert harness.prices.history_requests == []


async def test_a_history_shorter_than_the_strategys_window_offers_no_backtest() -> None:
    harness = build_harness()
    harness.list_stock("2330", bars([100.0 + day for day in range(100)]))

    assert (await harness.pipeline.load_backtest_options())[1] is None

    with pytest.raises(BacktestPeriodUnavailable, match="No backtest can run yet"):
        await harness.pipeline.run_backtest(inputs())


@pytest.mark.parametrize(
    ("first", "last"), [(FIRST - timedelta(days=1), HISTORY_LAST_SESSION), (FIRST, HISTORY_LAST_SESSION + timedelta(days=1))]
)
async def test_a_period_outside_the_held_history_is_refused_with_what_may_be_covered_and_saves_nothing(
    first: date, last: date
) -> None:
    harness = market()

    with pytest.raises(BacktestPeriodUnavailable, match=f"A backtest can cover {FIRST} to {HISTORY_LAST_SESSION}"):
        await harness.pipeline.run_backtest(inputs(first, last))

    assert await harness.pipeline.load_backtests() == []


async def test_the_history_is_read_once_and_again_only_when_the_source_holds_another_session() -> None:
    harness = market()

    await harness.pipeline.run_backtest(inputs())
    await harness.pipeline.run_backtest(inputs(buy_score=85))

    assert sorted(harness.prices.history_requests) == ["2317", "2330", "2603"]

    next_session = HISTORY_LAST_SESSION + timedelta(days=1)
    harness.prices.history["2330"] = bars([100.0 + day for day in range(HELD_DAYS + 1)], next_session)
    longer = await harness.pipeline.run_backtest(inputs(last=next_session))

    assert len(harness.prices.history_requests) == 6
    assert longer.last_session == next_session


async def test_a_built_in_strategy_can_be_replayed_in_place_of_the_saved_one() -> None:
    harness = market()

    backtest = await harness.pipeline.run_backtest(inputs(first=HISTORY_LAST_SESSION - timedelta(days=3)), "balanced")

    assert (backtest.strategy_id, len(backtest.equity_curve)) == ("balanced", 4)


async def test_a_user_keeps_only_the_newest_saved_backtests() -> None:
    harness = market()
    harness.config.accounts.saved_backtests = 2

    for buy_score in (80, 85, 91):
        await harness.pipeline.run_backtest(inputs(buy_score=buy_score))
        harness.clock.current_time += timedelta(minutes=1)

    assert [backtest.inputs.buy_score for backtest in await harness.pipeline.load_backtests()] == [91, 85]


# ---------------------------------------------------------------------------- #
#                                  The storage                                 #
# ---------------------------------------------------------------------------- #


def saved_backtest(created_at: datetime) -> Backtest:
    """A backtest with a marked position, a sold trade, an open trade and a benchmark, so every stored part is read back."""
    session = created_at.date()
    account = Account(cash=400_000.5)
    account.buy("2330", 1000, 100.0, 100_142.0)
    trade = BacktestTrade(
        stock_id="2330",
        stock_name="TSMC",
        quantity=1000,
        bought_on=session,
        average_cost=100.142,
        pnl=-321.5,
        fee=142,
        tax=0,
        held_sessions=0,
    )
    sold = replace(trade, stock_id="2603", sold_on=session, sold_at=95.5, exit_source=SignalSource.STOP_LOSS, tax=286)

    return Backtest(
        created_at=created_at,
        strategy_id="trend",
        strategy_name="Trend",
        inputs=BacktestInputs(first=session, last=session, initial_cash=500_000, buy_score=80, sell_score=30),
        stop_loss_pct=0.1,
        risk_per_trade_pct=0.02,
        equity_curve={session: account},
        benchmark=bars([20_000.0], session),
        trades=[sold, trade],
    )


async def test_a_saved_backtest_reads_back_as_it_was_and_the_oldest_go_beyond_the_limit(database: DatabaseConnector) -> None:
    repository = SqlBacktestRepository(database.for_owner(UserId("alice")))
    first_at = datetime(2026, 10, 19, 14, 0, tzinfo=TAIWAN_TIMEZONE)
    first, second, third = (saved_backtest(first_at + timedelta(minutes=minute)) for minute in range(3))

    await repository.save(first, keep=2)
    await repository.save(second, keep=2)

    assert await repository.saved() == [second, first]
    assert await repository.get(first.backtest_id) == first

    await repository.save(third, keep=2)

    assert await repository.saved() == [third, second]
    assert await repository.get(first.backtest_id) is None
    assert (await repository.delete(second.backtest_id), await repository.delete(second.backtest_id)) == (True, False)
    assert await repository.saved() == [third]


# ---------------------------------------------------------------------------- #
#                                  The Web API                                 #
# ---------------------------------------------------------------------------- #


def body(**changes: Any) -> dict[str, Any]:
    document = {"first": str(FIRST), "last": str(HISTORY_LAST_SESSION), "initial_cash": 1_000_000, "buy_score": 80, "sell_score": 30}
    return {"inputs": document | changes}


async def test_the_api_runs_a_backtest_and_answers_it_with_its_summary_days_and_trades() -> None:
    harness = market()

    async with serve(harness) as client:
        response = await write(client, "POST", "/v1/backtests", body())
        answer = response.json()
        listed = (await client.get("/v1/backtests")).json()
        read = (await client.get(f"/v1/backtests/{answer['backtest_id']}")).json()

    [saved] = await harness.pipeline.load_backtests()
    last = answer["equity_curve"][str(HISTORY_LAST_SESSION)]

    assert response.status_code == 200, response.text
    assert (answer["strategy_id"], answer["inputs"], answer["first_session"]) == ("trend", body()["inputs"], str(FIRST))
    assert (answer["final_equity"], answer["total_return_pct"]) == (saved.final_equity, saved.total_return_pct)
    assert (answer["trade_count"], answer["winning_trades"], answer["fee"], answer["tax"]) == (2, 1, saved.fee, saved.tax)
    assert (len(answer["equity_curve"]), len(answer["benchmark"])) == (40, 40)
    assert (last["equity"], last["cash"], [position["stock_id"] for position in last["positions"]]) == (
        saved.final_equity,
        last["cash"],
        ["2330"],
    )
    assert [(trade["stock_id"], trade["exit_source"], trade["sold_on"] is None) for trade in answer["trades"]] == [
        ("2603", "stop_loss", False),
        ("2330", None, True),
    ]
    assert answer["trades"][0]["return_pct"] == saved.trades[0].return_pct
    assert read == answer
    assert listed == [{key: value for key, value in answer.items() if key not in {"equity_curve", "benchmark", "trades"}}]


async def test_the_api_offers_the_longest_period_and_the_live_defaults() -> None:
    async with serve(market()) as client:
        options = await client.get("/v1/backtests/options")

    assert (options.status_code, options.json()) == (200, {"strategy_id": "trend", "strategy_name": "Trend", **body()})


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"buy_score": 101}, "buy_score"),
        ({"sell_score": -1}, "sell_score"),
        ({"initial_cash": 0}, "initial_cash"),
        ({"first": "last spring"}, "first"),
        ({"first": str(HISTORY_LAST_SESSION), "last": str(FIRST)}, None),
    ],
)
async def test_the_api_refuses_invalid_inputs_at_their_field_and_runs_nothing(change: dict[str, Any], field: str | None) -> None:
    harness = market()

    async with serve(harness) as client:
        response = await write(client, "POST", "/v1/backtests", body(**change))

    expected = ["body", "inputs", field] if field else ["body", "inputs"]

    assert (response.status_code, response.json()["code"]) == (422, "invalid_request")
    assert [error["loc"] for error in response.json()["detail"]] == [expected]
    assert (await harness.pipeline.load_backtests(), harness.prices.history_requests) == ([], [])


async def test_the_api_refuses_a_period_outside_the_held_history_and_says_what_is_available() -> None:
    harness = market()

    async with serve(harness) as client:
        response = await write(client, "POST", "/v1/backtests", body(first=str(FIRST - timedelta(days=30))))

    assert (response.status_code, response.json()["code"]) == (422, "backtest_period_unavailable")
    assert f"A backtest can cover {FIRST} to {HISTORY_LAST_SESSION}" in response.json()["detail"]
    assert await harness.pipeline.load_backtests() == []


async def test_a_saved_backtest_is_its_users_alone_to_read_and_delete() -> None:
    harness = market()
    harness.users.add(MEMBER, MEMBER_PASSWORD)

    async with app_of(harness) as app, client_at(app) as administrator, client_at(app) as member:
        await sign_in(administrator, harness.administrator.username, ADMINISTRATOR_PASSWORD)
        await sign_in(member, MEMBER.username, MEMBER_PASSWORD)
        backtest_id = (await write(administrator, "POST", "/v1/backtests", body())).json()["backtest_id"]
        others = [
            (await member.get("/v1/backtests")).json(),
            (await member.get(f"/v1/backtests/{backtest_id}")).status_code,
            (await write(member, "POST", f"/v1/backtests/{backtest_id}/delete", {})).status_code,
        ]
        kept = (await administrator.get(f"/v1/backtests/{backtest_id}")).status_code
        deleted = (await write(administrator, "POST", f"/v1/backtests/{backtest_id}/delete", {})).status_code
        gone = await administrator.get(f"/v1/backtests/{backtest_id}")

    assert others == [[], 404, 404]
    assert (kept, deleted, gone.status_code, gone.json()["code"]) == (200, 204, 404, "not_found")
