from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from trading_stack import MONDAY_10_00, SilentLogger, analysed_stock, open_stack, run_stats

from a_domain.model.system.user import User
from a_domain.model.trading.order import Order
from a_domain.types.enums import ExecutionProvider, OrderStatus, OrderType, Role, SignalSource, TimeInForce, TradeAction, Workflow
from a_domain.types.ids import RunId, UserId, new_decision_id
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.trading_journal import TradingJournal
from c_infrastructure.database.repositories.user_store import SqlUserStore
from c_infrastructure.database.repositories.users_orders import SqlUsersOrders

pytestmark = pytest.mark.asyncio


async def test_a_run_reads_back_with_its_decision_and_its_order(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    stock = analysed_stock()

    order = (await stack.pipeline.buy_manually(stock)).require_manual_buy_order()

    assert isinstance(order, Order) and order.status == OrderStatus.FILLED
    run = await stack.journal.find_run(order.run_id)
    [signal] = await stack.journal.signals_of(order.run_id)

    assert run is not None
    assert (run.workflow, run.signals_generated, run.orders_submitted, run.end_time is not None) == (Workflow.MANUAL_BUY, 1, 1, True)
    assert (signal.decision_id, signal.stock_id, signal.action, signal.source) == (
        order.decision_id,
        "2330",
        TradeAction.BUY,
        SignalSource.MANUAL,
    )
    assert (signal.technical_report, signal.ai_report) == (stock.technical_report, stock.ai_report)
    assert await stack.journal.orders_of(order.run_id) == [order]


async def test_recent_runs_come_newest_first_up_to_the_limit(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    run_ids = []

    for _ in range(3):
        stack.clock.current += timedelta(minutes=1)

        async with stack.run_history.execute(Workflow.INTRADAY) as stats:
            run_ids.append(stats.run_id)

    assert [run.run_id for run in await stack.journal.recent_runs(limit=2)] == [run_ids[2], run_ids[1]]


async def test_an_unknown_run_has_no_record_decisions_or_orders(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    await stack.pipeline.buy_manually(analysed_stock())
    unknown = RunId(uuid4())

    assert (
        await stack.journal.find_run(unknown),
        await stack.journal.signals_of(unknown),
        await stack.journal.orders_of(unknown),
    ) == (None, [], [])


async def test_the_orders_to_settle_are_the_unconfirmed_ones_of_the_runs_on_the_broker_that_ended(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    ended, running, on_mock = (run_stats(Workflow.MANUAL_BUY) for _ in range(3))
    ended.end_time = ended.start_time
    on_mock.end_time = on_mock.start_time
    on_sinopac = [
        replace(ended, execution_provider=ExecutionProvider.SHIOAJI),
        replace(running, execution_provider=ExecutionProvider.SHIOAJI),
    ]

    for run in [*on_sinopac, on_mock]:
        await stack.journal.save_run(run)

    lost, in_flight, filled, mock = (journal_order(run.run_id) for run in (*on_sinopac, on_sinopac[0], on_mock))
    for order in (lost, in_flight, mock):
        order.leave_unconfirmed("the broker's answer was lost", now=order.created_at)
    filled.submit(now=filled.created_at)
    filled.fill(1000, 100.0, 142, 0, now=filled.created_at)

    for order in (lost, in_flight, filled, mock):
        await stack.journal.save_order(order)

    assert await stack.journal.unsettled_orders(ExecutionProvider.SHIOAJI) == [lost], "not one of a run still under way"
    assert await stack.journal.unsettled_orders(ExecutionProvider.MOCK) == [mock]


async def test_the_runs_an_earlier_process_left_are_those_on_the_broker_without_an_end_that_started_before_it(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    left, ended, later, on_mock = (
        replace(run_stats(Workflow.MANUAL_BUY), execution_provider=ExecutionProvider.SHIOAJI) for _ in range(4)
    )
    ended.end_time = ended.start_time
    later.start_time = left.start_time + timedelta(minutes=2)
    on_mock = replace(on_mock, execution_provider=ExecutionProvider.MOCK)

    for run in (left, ended, later, on_mock):
        await stack.journal.save_run(run)

    started = left.start_time + timedelta(minutes=1)
    assert [run.run_id for run in await stack.journal.unfinished_runs(ExecutionProvider.SHIOAJI, started)] == [left.run_id]


async def test_the_orders_every_user_has_awaiting_settlement_are_counted_one_user_at_a_time(database: DatabaseConnector) -> None:
    users = SqlUserStore(database, SecretStr("A" * 43), SilentLogger())
    owners = [UserId("u-alice"), UserId("u-bob")]

    for user_id in owners:
        named = User(user_id=user_id, username=user_id, email=f"{user_id}@example.com", role=Role.USER, created_at=MONDAY_10_00)
        await users.create(named, SecretStr("a long enough password"))
        journal = TradingJournal(database.for_owner(user_id))
        run = replace(run_stats(Workflow.MANUAL_BUY), execution_provider=ExecutionProvider.SHIOAJI)
        await journal.save_run(run)
        lost, filled = journal_order(run.run_id), journal_order(run.run_id)
        lost.leave_unconfirmed("the broker's answer was lost", now=lost.created_at)
        filled.submit(now=filled.created_at)
        filled.fill(1000, 100.0, 142, 0, now=filled.created_at)
        await journal.save_order(lost)
        await journal.save_order(filled)

    assert await SqlUsersOrders(database).awaiting_settlement(ExecutionProvider.SHIOAJI) == 2
    assert await SqlUsersOrders(database).awaiting_settlement(ExecutionProvider.MOCK) == 0


def journal_order(run_id: RunId) -> Order:
    at = datetime(2026, 10, 19, 1, 30, tzinfo=UTC)
    return Order(
        run_id=run_id,
        decision_id=new_decision_id(),
        stock_id="2330",
        action=TradeAction.BUY,
        order_type=OrderType.LIMIT,
        quantity=1000,
        limit_price=100.0,
        price_at_signal=100.0,
        time_in_force=TimeInForce.IOC,
        created_at=at,
        updated_at=at,
    )
