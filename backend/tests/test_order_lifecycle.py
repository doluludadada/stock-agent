from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from a_domain.model.trading.order import Order
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.types.enums import OrderStatus, OrderType, RejectReason, TimeInForce, TradeAction
from a_domain.types.errors import IllegalOrderTransition
from a_domain.types.ids import new_decision_id, new_run_id

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)

COSTS = TradingCostRule(
    fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20, bond_etf_tax_exempt_until=date(2026, 12, 31)
)

LEGAL = {
    (OrderStatus.PENDING, OrderStatus.SUBMITTED),
    (OrderStatus.PENDING, OrderStatus.UNCONFIRMED),
    (OrderStatus.PENDING, OrderStatus.REJECTED),
    (OrderStatus.PENDING, OrderStatus.FAILED),
    (OrderStatus.PENDING, OrderStatus.CANCELLED),
    (OrderStatus.SUBMITTED, OrderStatus.SUBMITTED),
    (OrderStatus.SUBMITTED, OrderStatus.UNCONFIRMED),
    (OrderStatus.SUBMITTED, OrderStatus.FILLED),
    (OrderStatus.SUBMITTED, OrderStatus.CANCELLED),
    (OrderStatus.SUBMITTED, OrderStatus.FAILED),
    (OrderStatus.UNCONFIRMED, OrderStatus.SUBMITTED),
    (OrderStatus.UNCONFIRMED, OrderStatus.UNCONFIRMED),
    (OrderStatus.UNCONFIRMED, OrderStatus.FILLED),
    (OrderStatus.UNCONFIRMED, OrderStatus.CANCELLED),
    (OrderStatus.UNCONFIRMED, OrderStatus.REJECTED),
    (OrderStatus.UNCONFIRMED, OrderStatus.FAILED),
}
"""An UNCONFIRMED order may end any way the broker's record says, or stay UNCONFIRMED; nothing that ended moves again."""


def new_order(action: TradeAction = TradeAction.BUY, quantity: int = 1000) -> Order:
    return Order(
        run_id=new_run_id(),
        decision_id=new_decision_id(),
        stock_id="2330",
        action=action,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=100,
        price_at_signal=100,
        time_in_force=TimeInForce.IOC,
        created_at=NOW,
        updated_at=NOW,
    )


def fill(order: Order, quantity: int) -> None:
    cost = COSTS.apply(order.action, "2330", 100, quantity, now=NOW)
    order.fill(quantity, 100, cost.fee, cost.tax, now=NOW)


def order_in(status: OrderStatus) -> Order:
    order = new_order()
    setup: dict[OrderStatus, Callable[[], None]] = {
        OrderStatus.PENDING: lambda: None,
        OrderStatus.SUBMITTED: lambda: order.submit(now=NOW),
        OrderStatus.UNCONFIRMED: lambda: order.leave_unconfirmed("the broker's answer was lost", now=NOW),
        OrderStatus.FILLED: lambda: (order.submit(now=NOW), fill(order, order.quantity)),
        OrderStatus.CANCELLED: lambda: order.cancel("user cancelled", now=NOW),
        OrderStatus.REJECTED: lambda: order.reject(RejectReason.INSUFFICIENT_CASH, "needs 100,142", now=NOW),
        OrderStatus.FAILED: lambda: order.fail("broker unreachable", now=NOW),
    }
    setup[status]()
    assert order.status == status
    return order


def move(order: Order, target: OrderStatus) -> None:
    if target == OrderStatus.SUBMITTED and order.status == OrderStatus.SUBMITTED:
        fill(order, 1)
    elif target == OrderStatus.SUBMITTED:
        order.submit(now=NOW)
    elif target == OrderStatus.UNCONFIRMED:
        order.leave_unconfirmed("a part still works after a cancel request", now=NOW)
    elif target == OrderStatus.FILLED:
        fill(order, order.remaining_quantity or 1)
    elif target == OrderStatus.CANCELLED:
        order.cancel("cancel requested", now=NOW)
    elif target == OrderStatus.REJECTED:
        order.reject(RejectReason.MARKET_CLOSED, "closed at 14:00", now=NOW)
    elif target == OrderStatus.FAILED:
        order.fail("exception", now=NOW)


TARGETS = [status for status in OrderStatus if status != OrderStatus.PENDING]


@pytest.mark.parametrize("source", list(OrderStatus))
@pytest.mark.parametrize("target", TARGETS)
def test_every_status_change_is_legal_only_if_the_lifecycle_allows_it(source: OrderStatus, target: OrderStatus) -> None:
    order = order_in(source)

    if (source, target) in LEGAL:
        move(order, target)
        assert order.status == target
        return

    with pytest.raises(IllegalOrderTransition):
        move(order, target)

    assert order.status == source


@pytest.mark.parametrize("status", list(OrderStatus))
def test_a_pending_submitted_or_unconfirmed_order_is_open_and_only_one_that_awaits_no_settlement_fails_late(
    status: OrderStatus,
) -> None:
    order = order_in(status)
    is_open = status in {OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.UNCONFIRMED}

    assert (order.status.is_open, order.status.fill_final) == (is_open, not is_open and status != OrderStatus.FAILED)

    order.fail_if_open("broker call failed", now=NOW)

    assert order.status == (OrderStatus.FAILED if is_open and status != OrderStatus.UNCONFIRMED else status)


def test_a_partial_fill_of_an_unconfirmed_order_the_broker_lists_submits_it_and_keeps_it_working() -> None:
    order = order_in(OrderStatus.UNCONFIRMED)

    order.submit(now=NOW)
    fill(order, 400)

    assert (order.status, order.filled_quantity, order.reason) == (OrderStatus.SUBMITTED, 400, None)


def test_nothing_moves_an_order_back_to_pending() -> None:
    assert not any(OrderStatus.PENDING in {target for source, target in LEGAL if source == status} for status in OrderStatus)


def test_partial_fills_accumulate_price_quantity_fee_and_tax() -> None:
    order = new_order(action=TradeAction.SELL)
    order.submit(now=NOW)

    cost = COSTS.apply(TradeAction.SELL, "2330", 100, 400, now=NOW)
    order.fill(400, 100, cost.fee, cost.tax, realized_pnl=1_000, now=NOW)
    cost = COSTS.apply(TradeAction.SELL, "2330", 110, 600, now=NOW)
    order.fill(600, 110, cost.fee, cost.tax, realized_pnl=2_000, now=NOW)

    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == 1000
    assert order.average_filled_price == pytest.approx(106)
    assert (order.fee, order.tax, order.realized_pnl) == (57 + 94, 120 + 198, 3_000)


def test_cancelling_a_partly_filled_order_keeps_what_was_filled() -> None:
    order = order_in(OrderStatus.SUBMITTED)
    fill(order, 400)

    order.cancel("IOC remainder cancelled", now=NOW)

    assert (order.status, order.filled_quantity, order.reason) == (OrderStatus.CANCELLED, 400, "IOC remainder cancelled")


@pytest.mark.parametrize("fills", [[329], [100, 229], [1] * 329], ids=["one fill", "two fills", "a share at a time"])
def test_fills_at_the_limit_average_exactly_the_limit(fills: list[int]) -> None:
    order = replace(new_order(quantity=329), limit_price=12.45)
    order.submit(now=NOW)

    for shares in fills:
        order.fill(shares, 12.45, 0, 0, now=NOW)

    assert (order.status, order.average_filled_price) == (OrderStatus.FILLED, 12.45)


def test_a_fill_beyond_the_limit_price_is_refused() -> None:
    order = order_in(OrderStatus.SUBMITTED)

    with pytest.raises(ValueError, match="BUY fill price cannot exceed limit_price"):
        cost = COSTS.apply(TradeAction.BUY, "2330", 101, 1, now=NOW)
        order.fill(1, 101, cost.fee, cost.tax, now=NOW)

    assert (order.status, order.filled_quantity) == (OrderStatus.SUBMITTED, 0)


@pytest.mark.parametrize("terminal", [OrderStatus.FAILED, OrderStatus.CANCELLED, OrderStatus.UNCONFIRMED])
def test_failures_cancels_and_unconfirmed_orders_need_a_reason(terminal: OrderStatus) -> None:
    order = new_order()
    events = {OrderStatus.FAILED: order.fail, OrderStatus.CANCELLED: order.cancel, OrderStatus.UNCONFIRMED: order.leave_unconfirmed}

    with pytest.raises(ValueError, match="requires a reason"):
        events[terminal](" ", now=NOW)

    assert order.status == OrderStatus.PENDING


def test_a_rejection_reads_as_its_reason_code_then_detail() -> None:
    order = new_order()

    order.reject(RejectReason.STALE_PRICE, "quote from 09:59 is 21 min old", now=NOW)

    assert order.reason == "STALE_PRICE: quote from 09:59 is 21 min old"


def test_hold_cannot_be_an_order() -> None:
    with pytest.raises(ValueError):
        new_order(action=TradeAction.HOLD)


@pytest.mark.parametrize(("filled", "said"), [(0, "@ 100.0"), (430, "@ 99.5")], ids=["nothing filled", "filled below the limit"])
def test_the_summary_shows_the_average_filled_price_once_something_filled_and_the_limit_before(filled: int, said: str) -> None:
    order = order_in(OrderStatus.SUBMITTED)

    if filled:
        cost = COSTS.apply(TradeAction.BUY, "2330", 99.5, filled, now=NOW)
        order.fill(filled, 99.5, cost.fee, cost.tax, now=NOW)

    assert f"filled {filled}/1000 {said}," in order.summary
