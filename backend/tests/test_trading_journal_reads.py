from uuid import uuid4

import pytest
from trading_stack import analysed_stock, open_stack

from a_domain.model.trading.order import Order
from a_domain.types.enums import OrderStatus, SignalSource, TradeAction, Workflow
from a_domain.types.ids import RunId

pytestmark = pytest.mark.asyncio


async def test_a_run_reads_back_with_its_decision_and_its_order(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    stock = analysed_stock()

    order = await stack.manual_buy.execute(stock)

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
        async with stack.run_history.open(Workflow.INTRADAY) as status:
            run_ids.append(status.stats.run_id)

    assert [run.run_id for run in await stack.journal.recent_runs(limit=2)] == [run_ids[2], run_ids[1]]


async def test_an_unknown_run_has_no_record_decisions_or_orders(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    await stack.manual_buy.execute(analysed_stock())
    unknown = RunId(uuid4())

    assert (
        await stack.journal.find_run(unknown),
        await stack.journal.signals_of(unknown),
        await stack.journal.orders_of(unknown),
    ) == (None, [], [])
