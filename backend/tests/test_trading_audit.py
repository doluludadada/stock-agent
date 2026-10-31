import asyncio
from datetime import UTC, timedelta

import pytest
from sqlmodel import col, select
from trading_stack import MONDAY_10_00, analysed_stock, bar, open_stack

from a_domain.model.analysis.ai_analysis_report import AiAnalysisReport
from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.trading.order import Order
from a_domain.types.enums import OrderMode, OrderStatus, SignalSource, TradeAction, Workflow
from c_infrastructure.database.models.trading_journal_dto import AccountSnapshotDTO, OrderDTO, TradeSignalDTO, WorkflowRunDTO
from c_infrastructure.database.repositories.trading_journal import TradingJournal

pytestmark = pytest.mark.asyncio


def stored_utc(moment):
    """The journal keeps every timestamp as UTC wall-clock time, because SQLite keeps no zone."""
    return moment.replace(tzinfo=UTC)


async def test_an_order_row_traces_back_to_its_price_reports_signal_run_and_result(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    stock = analysed_stock()

    await stack.pipeline.buy_manually(stock)

    async with stack.db.get_session() as session:
        order_row = (await session.execute(select(OrderDTO))).scalar_one()
        signal_row = await session.get(TradeSignalDTO, order_row.decision_id)
        run_row = await session.get(WorkflowRunDTO, order_row.run_id)
        snapshot_row = (
            await session.execute(select(AccountSnapshotDTO).where(col(AccountSnapshotDTO.order_id) == order_row.id))
        ).scalar_one()

    assert signal_row is not None and run_row is not None
    quote = stack.quotes.realtime["2330"]

    assert (signal_row.price_at_signal, stored_utc(signal_row.price_observed_at)) == (quote.close, quote.ts)
    assert stored_utc(signal_row.history_until) == stock.ohlcv[-1].ts
    assert TechnicalReport(**signal_row.technical_report) == stock.technical_report
    assert AiAnalysisReport(**signal_row.ai_report) == stock.ai_report
    assert (signal_row.action, signal_row.source, signal_row.run_id) == (TradeAction.BUY, SignalSource.MANUAL, order_row.run_id)
    assert (run_row.workflow, run_row.execution_provider, run_row.end_time is not None) == (Workflow.MANUAL_BUY, "mock", True)
    assert (order_row.status, order_row.filled_quantity, order_row.limit_price, order_row.fee, order_row.tax) == (
        OrderStatus.FILLED,
        2000,
        100,
        285,
        0,
    )
    assert snapshot_row.cash == 1_000_000 - 200_285
    assert snapshot_row.positions == [{"stock_id": "2330", "quantity": 2000, "average_cost": 100.1425, "mark_price": 100.0}]


async def test_a_filled_manual_buy_returns_the_filled_order(tmp_path) -> None:
    stack = await open_stack(tmp_path)

    result = (await stack.pipeline.buy_manually(analysed_stock())).require_manual_buy_order()

    assert isinstance(result, Order)
    assert (result.status, result.filled_quantity, result.fee) == (OrderStatus.FILLED, 2000, 285)


@pytest.mark.parametrize(
    ("setup", "reason"),
    [("market_closed", "MARKET_CLOSED"), ("order_mode_disabled", "ORDER_MODE_DISABLED"), ("stale_price", "STALE_PRICE")],
)
async def test_a_refused_manual_buy_is_a_recorded_rejected_order_with_its_reason(tmp_path, setup: str, reason: str) -> None:
    configure = (lambda config: setattr(config.trading, "order_mode", OrderMode.DISABLED)) if setup == "order_mode_disabled" else None
    stack = await open_stack(tmp_path, configure=configure or (lambda config: None))

    if setup == "market_closed":
        stack.clock.current = MONDAY_10_00.replace(hour=14)

    if setup == "stale_price":
        stack.quotes.realtime["2330"] = bar(MONDAY_10_00 - timedelta(minutes=30), 100)

    result = (await stack.pipeline.buy_manually(analysed_stock())).require_manual_buy_order()

    assert isinstance(result, Order)
    assert result.status == OrderStatus.REJECTED and result.reason is not None and result.reason.startswith(reason)

    async with stack.db.get_session() as session:
        row = (await session.execute(select(OrderDTO))).scalar_one()

    assert (row.id, row.status, row.reason, row.fee) == (result.id, OrderStatus.REJECTED, result.reason, 0)
    assert (await stack.broker.get_account()).cash == 1_000_000


@pytest.mark.parametrize(
    ("hour", "minute", "status", "reason"),
    [
        (8, 45, OrderStatus.REJECTED, "MARKET_CLOSED: Mon 2026-10-19 08:45 falls in the market's opening_auction phase"),
        (9, 0, OrderStatus.FILLED, None),
        (13, 24, OrderStatus.FILLED, None),
        (13, 25, OrderStatus.REJECTED, "MARKET_CLOSED: Mon 2026-10-19 13:25 falls in the market's closing_auction phase"),
        (13, 29, OrderStatus.REJECTED, "MARKET_CLOSED: Mon 2026-10-19 13:29 falls in the market's closing_auction phase"),
    ],
)
async def test_only_continuous_trading_takes_the_apps_ioc_orders(
    tmp_path, hour: int, minute: int, status: OrderStatus, reason: str | None
) -> None:
    stack = await open_stack(tmp_path)
    stack.clock.current = MONDAY_10_00.replace(hour=hour, minute=minute)
    stack.quotes.realtime["2330"] = bar(stack.clock.current - timedelta(minutes=1), 100)

    result = (await stack.pipeline.buy_manually(analysed_stock())).require_manual_buy_order()

    assert isinstance(result, Order)
    assert result.status == status
    assert reason is None or (result.reason is not None and result.reason.startswith(reason))


@pytest.mark.parametrize(
    ("initial_cash", "composite_score", "reason"),
    [(50, 90, "Manual BUY not sized: cash 50 buys no share of 2330"), (1_000_000, None, "analysis incomplete")],
)
async def test_a_manual_buy_that_cannot_become_an_order_says_why(
    tmp_path, initial_cash: float, composite_score: int | None, reason: str
) -> None:
    stack = await open_stack(tmp_path, configure=lambda config: setattr(config.mock_trading, "initial_cash", initial_cash))

    status = await stack.pipeline.buy_manually(analysed_stock(composite_score=composite_score))

    assert status.manual_buy_refusal is not None and status.manual_buy_refusal.startswith(reason)

    async with stack.db.get_session() as session:
        assert (await session.execute(select(OrderDTO))).first() is None


class UnwritableSignals(TradingJournal):
    async def save_signals(self, run_id, signals) -> None:
        raise OSError("disk full")


async def test_a_decision_that_cannot_be_recorded_sends_no_order(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    stack = await open_stack(tmp_path, journal=UnwritableSignals(db=stack.db))

    status = await stack.pipeline.buy_manually(analysed_stock())

    assert status.manual_buy_refusal is not None and "disk full" in status.manual_buy_refusal
    assert ((await stack.broker.get_account()).cash, (await stack.broker.get_account()).positions) == (1_000_000, [])


async def test_a_decision_gets_one_order_however_often_it_is_executed(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    stock = analysed_stock()
    stock.realtime_bar = stack.quotes.realtime["2330"]
    signal = stack.config.decision_rule().entry_rule.decide_manual(stock, await stack.broker.get_account(), now=stack.clock.now())

    async with stack.run_history.open(Workflow.MANUAL_BUY) as status:
        await stack.journal.save_signals(status.stats.run_id, [signal])
        await stack.order_execution.execute([signal], status)
        await stack.order_execution.execute([signal], status)

    assert [order.status for order in status.orders] == [OrderStatus.FILLED]
    assert [position.quantity for position in (await stack.broker.get_account()).positions] == [2000]


class BrokerThatChecksTheRecord:
    def __init__(self, stack) -> None:
        self.stack = stack
        self.recorded_before_sending: list[OrderStatus] = []

    async def place_order(self, order: Order) -> Order:
        async with self.stack.db.get_session() as session:
            row = await session.get(OrderDTO, order.id)
            self.recorded_before_sending.append(row.status if row else None)

        return await self.stack.broker.place_order(order)

    async def get_account(self):
        return await self.stack.broker.get_account()


async def test_the_order_is_recorded_pending_before_the_broker_sees_it(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    broker = BrokerThatChecksTheRecord(stack)
    stack.order_execution._execution_provider = broker

    await stack.pipeline.buy_manually(analysed_stock())

    assert broker.recorded_before_sending == [OrderStatus.PENDING]


async def test_a_run_is_recorded_when_it_starts_and_when_it_aborts(tmp_path) -> None:
    stack = await open_stack(tmp_path)

    with pytest.raises(RuntimeError):
        async with stack.run_history.open(Workflow.INTRADAY) as status:
            async with stack.db.get_session() as session:
                started = await session.get(WorkflowRunDTO, status.stats.run_id)
                assert started is not None and started.end_time is None

            raise RuntimeError("Yahoo hung")

    async with stack.db.get_session() as session:
        ended = await session.get(WorkflowRunDTO, status.stats.run_id)

    assert ended is not None and ended.end_time is not None
    assert ended.errors == ["Run aborted: RuntimeError: Yahoo hung"]


class SlowBroker:
    """The mock broker behind a gate: place_order waits until the test opens it, as a slow broker call does."""

    def __init__(self, stack) -> None:
        self.stack = stack
        self.called = asyncio.Event()
        self.gate = asyncio.Event()

    async def place_order(self, order: Order) -> Order:
        self.called.set()
        await self.gate.wait()
        return await self.stack.broker.place_order(order)

    async def get_account(self):
        return await self.stack.broker.get_account()


async def cancel_during_the_broker_call(stack, cancels: int) -> None:
    broker = SlowBroker(stack)
    stack.order_execution._execution_provider = broker
    run = asyncio.create_task(stack.pipeline.buy_manually(analysed_stock()))
    await broker.called.wait()

    for _ in range(cancels):
        run.cancel()
        await asyncio.sleep(0.01)

    broker.gate.set()

    with pytest.raises(asyncio.CancelledError):
        await run


async def recorded_orders(stack) -> list[tuple[OrderStatus, int, str | None]]:
    async with stack.db.get_session() as session:
        rows = (await session.execute(select(OrderDTO))).scalars().all()

    return [(row.status, row.filled_quantity, row.reason) for row in rows]


async def test_a_cancel_during_the_broker_call_lets_the_call_finish_and_records_what_the_broker_did(tmp_path) -> None:
    stack = await open_stack(tmp_path)

    await cancel_during_the_broker_call(stack, cancels=1)

    assert await recorded_orders(stack) == [(OrderStatus.FILLED, 2000, None)]
    assert [position.quantity for position in (await stack.broker.get_account()).positions] == [2000]


async def test_a_second_cancel_that_stops_the_broker_call_records_the_order_failed(tmp_path) -> None:
    stack = await open_stack(tmp_path)

    await cancel_during_the_broker_call(stack, cancels=2)

    [(status, filled, reason)] = await recorded_orders(stack)
    assert (status, filled) == (OrderStatus.FAILED, 0)
    assert reason is not None and "cancelled during the broker call" in reason
