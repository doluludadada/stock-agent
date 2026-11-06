"""
The Web API's follow of a finished Full Cycle and the mock account's trades and reset, as the web app reaches them:
the follow runs in the background through the same order gates and journal as every order, on the mock broker only,
and a second follow of a run with nothing left to follow is refused without recording anything.
"""

from datetime import timedelta

import pytest
from support.harness import MARKET_CLOSED, MARKET_OPEN, build_harness, harness_config, real_broker_config, rising_history
from support.web import ended, hold_stock_list, serve, write

from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.signal import TradeSignal
from a_domain.types.enums import Audience, ExecutionProvider, OrderMode, SignalSource, TradeAction, Workflow
from a_domain.types.ids import RunId

pytestmark = pytest.mark.asyncio

YESTERDAY_CLOSE = (MARKET_OPEN - timedelta(days=1)).replace(hour=13, minute=30)


async def recorded_full_cycle(harness, quantity: int = 1000) -> RunId:
    """A finished Full Cycle in the administrator's journal that decided to BUY 2330, priced at yesterday's close."""
    run = SystemStats(
        workflow=Workflow.FULL_CYCLE,
        execution_provider=ExecutionProvider.MOCK,
        order_mode=OrderMode.MOCK_ONLY,
        start_time=YESTERDAY_CLOSE + timedelta(hours=6),
        end_time=YESTERDAY_CLOSE + timedelta(hours=6, minutes=15),
    )
    buy = TradeSignal(
        stock_id="2330",
        action=TradeAction.BUY,
        source=SignalSource.COMBINED,
        score=85,
        reason="trend",
        quantity=quantity,
        generated_at=run.start_time,
        price_at_signal=98,
        price_observed_at=YESTERDAY_CLOSE,
    )
    await harness.journal.save_run(run)
    await harness.journal.save_signals(run.run_id, [buy])
    return run.run_id


async def test_a_follow_orders_the_runs_buy_at_a_fresh_quote_lists_the_trade_and_is_not_repeated() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    run_id = await recorded_full_cycle(harness)

    async with serve(harness) as client:
        offered = (await client.get(f"/v1/runs/{run_id}/follow")).json()
        started = await write(client, "POST", f"/v1/runs/{run_id}/follow", {})
        follow = await ended(client, started.json()["run_id"])
        trades = (await client.get("/v1/account/trades")).json()
        after = (await client.get(f"/v1/runs/{run_id}/follow")).json()
        again = await write(client, "POST", f"/v1/runs/{run_id}/follow", {})

    [order] = harness.broker.placed
    assert (offered["refusal"], len(offered["open_decision_ids"]), offered["follows"]) == (None, 1, [])
    assert (started.status_code, follow["state"], follow["summary"]["workflow"]) == (202, "finished", "follow")
    assert follow["summary"]["followed_run_id"] == str(run_id)
    assert (order.stock_id, order.action, order.quantity, order.limit_price) == ("2330", TradeAction.BUY, 1000, 100)
    assert [(trade["order"]["id"], trade["run"]["run_id"], trade["run"]["workflow"]) for trade in trades] == [
        (str(order.id), str(run_id), "full_cycle")
    ]
    assert (after["refusal"], after["open_decision_ids"], len(after["follows"])) == ("nothing_to_follow", [], 1)
    assert (again.status_code, again.json()["code"]) == (409, "nothing_to_follow")
    assert len(harness.broker.placed) == 1


async def test_a_follow_outside_continuous_trading_is_refused_and_records_nothing() -> None:
    harness = build_harness(now=MARKET_CLOSED)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    run_id = await recorded_full_cycle(harness)

    async with serve(harness) as client:
        refused = await write(client, "POST", f"/v1/runs/{run_id}/follow", {})
        offered = (await client.get(f"/v1/runs/{run_id}/follow")).json()

    assert (refused.status_code, refused.json()["code"], offered["refusal"]) == (409, "outside_follow_window", "outside_follow_window")
    assert (list(harness.journal.runs), harness.broker.placed) == ([run_id], [])


async def test_a_follow_priced_on_realtime_quotes_is_refused_where_the_runtime_has_none_and_records_nothing() -> None:
    harness = build_harness(realtime_quotes=False)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    run_id = await recorded_full_cycle(harness)

    async with serve(harness) as client:
        refused = await write(client, "POST", f"/v1/runs/{run_id}/follow", {})
        offered = await client.get(f"/v1/runs/{run_id}/follow")

    assert (refused.status_code, refused.json()["code"], offered.status_code) == (403, "realtime_quotes_unavailable", 200)
    assert (list(harness.journal.runs), harness.broker.placed) == ([run_id], [])


async def test_on_the_public_site_a_follow_needs_no_realtime_quote() -> None:
    harness = build_harness(now=MARKET_CLOSED, config=harness_config().model_copy(update={"audience": Audience.PUBLIC}))
    run_id = await recorded_full_cycle(harness)

    async with serve(harness) as client:
        started = await write(client, "POST", f"/v1/runs/{run_id}/follow", {})

    assert started.status_code == 202


async def test_an_unknown_run_has_no_follow() -> None:
    async with serve(build_harness()) as client:
        read = await client.get("/v1/runs/00000000-0000-0000-0000-000000000009/follow")
        started = await write(client, "POST", "/v1/runs/00000000-0000-0000-0000-000000000009/follow", {})

    assert (read.status_code, started.status_code) == (404, 404)


@pytest.mark.parametrize("path", ["/v1/runs/00000000-0000-0000-0000-000000000001/follow", "/v1/account/reset"])
async def test_a_real_broker_installation_offers_no_follow_and_no_reset(path: str) -> None:
    harness = build_harness(config=real_broker_config())

    async with serve(harness) as client:
        read = await client.get(path) if path.endswith("follow") else None
        written = await write(client, "POST", path, {"initial_cash": 500_000})

    assert (written.status_code, written.json()["code"]) == (403, "mock_broker_only")
    assert read is None or read.status_code == 403
    assert harness.broker.opening is None and harness.broker.placed == []


async def test_a_reset_opens_the_account_again_with_the_chosen_capital_and_the_history_says_so() -> None:
    harness = build_harness()

    async with serve(harness) as client:
        reset = await write(client, "POST", "/v1/account/reset", {"initial_cash": 2_500_000})
        history = (await client.get("/v1/account/history")).json()

    assert (reset.status_code, reset.json()["initial_cash"]) == (200, 2_500_000)
    assert (history["current"]["cash"], history["opening"]["initial_cash"], history["profit"]) == (2_500_000, 2_500_000, 0)


@pytest.mark.parametrize("initial_cash", [0, -1, "a lot"])
async def test_a_reset_needs_a_positive_starting_capital(initial_cash: object) -> None:
    harness = build_harness()

    async with serve(harness) as client:
        refused = await write(client, "POST", "/v1/account/reset", {"initial_cash": initial_cash})

    assert refused.status_code == 422
    assert harness.broker.opening is None


async def test_a_reset_waits_for_the_users_running_run() -> None:
    harness = build_harness()
    release = hold_stock_list(harness)

    async with serve(harness) as client:
        running = await write(client, "POST", "/v1/runs/full-cycle", {})
        refused = await write(client, "POST", "/v1/account/reset", {"initial_cash": 500_000})
        release.set()
        await ended(client, running.json()["run_id"])

    assert (refused.status_code, refused.json()["code"]) == (409, "run_in_progress")
    assert harness.broker.opening is None
