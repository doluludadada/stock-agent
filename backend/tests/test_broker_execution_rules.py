from datetime import UTC, datetime

import pytest

from a_domain.model.trading.broker_order_report import BrokerOrderReport
from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.execution import BrokerOutcomeRule, FillRule, LotSplitRule
from a_domain.types.enums import LotKind, OrderStatus, OrderType, TimeInForce, TradeAction
from a_domain.types.ids import new_decision_id, new_run_id

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)

COSTS = TradingCostRule(fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20)
OUTCOME = BrokerOutcomeRule(broker="Shioaji")


def new_order(action: TradeAction = TradeAction.BUY, quantity: int = 1500) -> Order:
    return Order(
        run_id=new_run_id(),
        decision_id=new_decision_id(),
        stock_id="2330",
        action=action,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=100,
        time_in_force=TimeInForce.IOC,
        created_at=NOW,
        updated_at=NOW,
    )


def report(status: OrderStatus, ordered: int = 1000, dealt: int = 0, reported: int | None = None) -> BrokerOrderReport:
    return BrokerOrderReport(
        stock_id="2330",
        status=status,
        ordered_shares=ordered,
        dealt_shares=dealt,
        reported_dealt_shares=dealt if reported is None else reported,
        fill_price=100.0 if dealt else None,
        description=f"{status} {ordered}",
    )


@pytest.mark.parametrize(
    ("board_lot_shares", "quantity", "parts"),
    [
        (1000, 2500, [(LotKind.BOARD_LOT, 2000), (LotKind.ODD_LOT, 500)]),
        (1000, 3000, [(LotKind.BOARD_LOT, 3000)]),
        (1000, 999, [(LotKind.ODD_LOT, 999)]),
        (100, 250, [(LotKind.BOARD_LOT, 200), (LotKind.ODD_LOT, 50)]),
    ],
)
def test_a_quantity_splits_into_whole_board_lots_and_the_odd_shares(board_lot_shares: int, quantity: int, parts: list) -> None:
    assert LotSplitRule(board_lot_shares=board_lot_shares).apply(quantity) == parts


@pytest.mark.parametrize(
    ("status", "done"),
    [
        (OrderStatus.PENDING, False),
        (OrderStatus.SUBMITTED, False),
        (OrderStatus.FILLED, True),
        (OrderStatus.CANCELLED, True),
        (OrderStatus.REJECTED, True),
        (OrderStatus.FAILED, True),
    ],
)
def test_an_exchange_order_is_done_once_its_status_is_final(status: OrderStatus, done: bool) -> None:
    assert report(status).is_done is done


@pytest.mark.parametrize(
    ("finished", "missing"),
    [
        (report(OrderStatus.FILLED, dealt=1000), False),
        (report(OrderStatus.CANCELLED, dealt=400), False),
        (report(OrderStatus.FILLED, dealt=400), True),
        (report(OrderStatus.CANCELLED, dealt=400, reported=600), True),
    ],
)
def test_deals_are_missing_when_they_fall_short_of_the_broker_count_or_of_a_filled_quantity(
    finished: BrokerOrderReport, missing: bool
) -> None:
    assert finished.deals_missing is missing


def test_a_buy_fill_costs_gross_plus_fee_and_realizes_nothing() -> None:
    cost, realized_pnl = FillRule(cost_rule=COSTS).apply(
        new_order(), 1000, 100, Position(stock_id="2330", quantity=500, average_cost=90)
    )

    assert (cost, realized_pnl) == (COSTS.apply(TradeAction.BUY, "2330", 100, 1000), None)


@pytest.mark.parametrize(
    ("held", "realized_pnl"), [(Position(stock_id="2330", quantity=1000, average_cost=90), 99_558 - 90_000), (None, None)]
)
def test_a_sell_fill_realizes_its_net_proceeds_less_the_cost_basis_of_held_shares(
    held: Position | None, realized_pnl: float | None
) -> None:
    cost, realized = FillRule(cost_rule=COSTS).apply(new_order(TradeAction.SELL, 1000), 1000, 100, held)

    assert (cost.net, realized) == (99_558, realized_pnl)


def test_a_filled_order_keeps_its_status() -> None:
    order = new_order(quantity=1000)
    order.submit(now=NOW)
    order.fill(1000, 100, COSTS.apply(TradeAction.BUY, "2330", 100, 1000), now=NOW)

    OUTCOME.apply(order, [report(OrderStatus.FILLED, dealt=1000)], NOW)

    assert (order.status, order.reason) == (OrderStatus.FILLED, None)


@pytest.mark.parametrize(
    ("reports", "status", "reason"),
    [
        (
            [report(OrderStatus.SUBMITTED)],
            OrderStatus.FAILED,
            "still working at the broker after a cancel request, check Shioaji: submitted 1000",
        ),
        (
            [report(OrderStatus.CANCELLED), report(OrderStatus.FAILED, 500)],
            OrderStatus.FAILED,
            "unexplained broker result: cancelled 1000; failed 500",
        ),
        ([report(OrderStatus.FILLED, dealt=400)], OrderStatus.FAILED, "unexplained broker result: filled 1000"),
        (
            [report(OrderStatus.REJECTED), report(OrderStatus.REJECTED, 500)],
            OrderStatus.REJECTED,
            "BROKER_REFUSED: rejected 1000; rejected 500",
        ),
        ([report(OrderStatus.CANCELLED)], OrderStatus.CANCELLED, "IOC unfilled: filled 0 of 1500; cancelled 1000"),
        (
            [report(OrderStatus.CANCELLED), report(OrderStatus.REJECTED, 500)],
            OrderStatus.CANCELLED,
            "IOC unfilled: filled 0 of 1500; cancelled 1000; rejected 500",
        ),
    ],
)
def test_the_parts_reports_give_an_unfilled_order_its_final_status(
    reports: list[BrokerOrderReport], status: OrderStatus, reason: str
) -> None:
    order = new_order()

    OUTCOME.apply(order, reports, NOW)

    assert (order.status, order.reason, order.updated_at) == (status, reason, NOW)


def test_a_partly_filled_order_is_cancelled_with_what_filled() -> None:
    order = new_order()
    order.submit(now=NOW)
    order.fill(1000, 100, COSTS.apply(TradeAction.BUY, "2330", 100, 1000), now=NOW)

    OUTCOME.apply(order, [report(OrderStatus.FILLED, dealt=1000), report(OrderStatus.REJECTED, 500)], NOW)

    assert (order.status, order.filled_quantity, order.reason) == (
        OrderStatus.CANCELLED,
        1000,
        "IOC unfilled: filled 1000 of 1500; filled 1000; rejected 500",
    )
