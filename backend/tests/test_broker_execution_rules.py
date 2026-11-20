from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from a_domain.model.trading.account import Account, BrokerFill, Position
from a_domain.model.trading.order import Order
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.execution import (
    BrokerOutcomeRule,
    ExchangeOrder,
    FillRule,
    LotSplitRule,
    OrderAcceptanceRule,
    PastSessionRule,
    SimulationCashRule,
)
from a_domain.types.enums import ExecutionProvider, LotKind, OrderStatus, OrderType, RejectReason, TimeInForce, TradeAction
from a_domain.types.ids import new_decision_id, new_run_id

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)

COSTS = TradingCostRule(
    fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20, bond_etf_tax_exempt_until=date(2026, 12, 31)
)
OUTCOME = BrokerOutcomeRule(broker="Shioaji")
ACCEPTANCE = OrderAcceptanceRule(cost_rule=COSTS)


def new_order(action: TradeAction = TradeAction.BUY, quantity: int = 1500) -> Order:
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


def part(status: OrderStatus, ordered: int = 1000, dealt: int = 0, reported: int | None = None) -> ExchangeOrder:
    return ExchangeOrder(
        stock_id="2330",
        status=status,
        ordered_shares=ordered,
        dealt_shares=dealt,
        reported_dealt_shares=dealt if reported is None else reported,
        fill_price=100.0 if dealt else None,
        description=f"{status} {ordered}",
    )


@pytest.mark.parametrize(
    ("order_type", "limit_price", "time_in_force", "refusal"),
    [
        (OrderType.LIMIT, 100, TimeInForce.IOC, None),
        (OrderType.LIMIT, 100, TimeInForce.FOK, None),
        (
            OrderType.LIMIT,
            100,
            TimeInForce.ROD,
            (RejectReason.UNSUPPORTED_TIME_IN_FORCE, "ROD would leave a working order at the broker that the app does not track"),
        ),
        (OrderType.MARKET, None, TimeInForce.IOC, (RejectReason.UNSUPPORTED_ORDER_TYPE, "the app sends LIMIT orders only")),
    ],
)
def test_a_broker_takes_only_limit_orders_that_leave_nothing_working(
    order_type: OrderType, limit_price: float | None, time_in_force: TimeInForce, refusal: tuple[RejectReason, str] | None
) -> None:
    placing = replace(new_order(), order_type=order_type, limit_price=limit_price, time_in_force=time_in_force)

    assert ACCEPTANCE.apply(placing, Account(cash=1_000_000)) == refusal


@pytest.mark.parametrize(
    ("action", "quantity", "account", "refusal"),
    [
        (TradeAction.BUY, 1000, Account(cash=100_142), None),
        (
            TradeAction.BUY,
            1000,
            Account(cash=100_141),
            (RejectReason.INSUFFICIENT_CASH, "needs 100,142 including fee, cash is 100,141"),
        ),
        (TradeAction.SELL, 1000, Account(cash=0), (RejectReason.POSITION_NOT_FOUND, "no 2330 shares held")),
        (TradeAction.SELL, 1000, Account(positions=[Position(stock_id="2330", quantity=1000, average_cost=90)]), None),
        (
            TradeAction.SELL,
            2000,
            Account(positions=[Position(stock_id="2330", quantity=1000, average_cost=90)]),
            (RejectReason.INSUFFICIENT_POSITION, "holds 1000, selling 2000"),
        ),
    ],
)
def test_a_broker_takes_a_buy_the_cash_pays_for_with_its_fee_and_a_sell_of_shares_held(
    action: TradeAction, quantity: int, account: Account, refusal: tuple[RejectReason, str] | None
) -> None:
    assert ACCEPTANCE.apply(new_order(action, quantity), account) == refusal


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
    ("finished", "missing"),
    [
        (part(OrderStatus.FILLED, dealt=1000), False),
        (part(OrderStatus.CANCELLED, dealt=400), False),
        (part(OrderStatus.FILLED, dealt=400), True),
        (part(OrderStatus.CANCELLED, dealt=400, reported=600), True),
    ],
)
def test_deals_are_missing_when_they_fall_short_of_the_broker_count_or_of_a_filled_quantity(
    finished: ExchangeOrder, missing: bool
) -> None:
    assert finished.deals_missing is missing


def test_a_buy_fill_costs_gross_plus_fee_and_realizes_nothing() -> None:
    cost, realized_pnl = FillRule(cost_rule=COSTS).apply(
        new_order(), 1000, 100, Position(stock_id="2330", quantity=500, average_cost=90), now=NOW
    )

    assert (cost, realized_pnl) == (COSTS.apply(TradeAction.BUY, "2330", 100, 1000, now=NOW), None)


@pytest.mark.parametrize(
    ("held", "realized_pnl"), [(Position(stock_id="2330", quantity=1000, average_cost=90), 99_558 - 90_000), (None, None)]
)
def test_a_sell_fill_realizes_its_net_proceeds_less_the_cost_basis_of_held_shares(
    held: Position | None, realized_pnl: float | None
) -> None:
    cost, realized = FillRule(cost_rule=COSTS).apply(new_order(TradeAction.SELL, 1000), 1000, 100, held, now=NOW)

    assert (cost.net, realized) == (99_558, realized_pnl)


def test_a_filled_order_keeps_its_status() -> None:
    order = new_order(quantity=1000)
    order.submit(now=NOW)
    cost = COSTS.apply(TradeAction.BUY, "2330", 100, 1000, now=NOW)
    order.fill(1000, 100, cost.fee, cost.tax, now=NOW)

    OUTCOME.apply(order, [part(OrderStatus.FILLED, dealt=1000)], NOW)

    assert (order.status, order.reason) == (OrderStatus.FILLED, None)


@pytest.mark.parametrize(
    ("parts", "status", "reason"),
    [
        (
            [part(OrderStatus.SUBMITTED)],
            OrderStatus.UNCONFIRMED,
            "unconfirmed at Shioaji, whose record of today settles it: submitted 1000",
        ),
        (
            [part(OrderStatus.CANCELLED), part(OrderStatus.UNCONFIRMED, 500)],
            OrderStatus.UNCONFIRMED,
            "unconfirmed at Shioaji, whose record of today settles it: cancelled 1000; unconfirmed 500",
        ),
        (
            [part(OrderStatus.CANCELLED), part(OrderStatus.FAILED, 500)],
            OrderStatus.FAILED,
            "unexplained broker result: cancelled 1000; failed 500",
        ),
        ([part(OrderStatus.FILLED, dealt=400)], OrderStatus.FAILED, "unexplained broker result: filled 1000"),
        (
            [part(OrderStatus.REJECTED), part(OrderStatus.REJECTED, 500)],
            OrderStatus.REJECTED,
            "BROKER_REFUSED: rejected 1000; rejected 500",
        ),
        ([part(OrderStatus.CANCELLED)], OrderStatus.CANCELLED, "IOC unfilled: filled 0 of 1500; cancelled 1000"),
        (
            [part(OrderStatus.CANCELLED), part(OrderStatus.REJECTED, 500)],
            OrderStatus.CANCELLED,
            "IOC unfilled: filled 0 of 1500; cancelled 1000; rejected 500",
        ),
    ],
)
def test_the_parts_reports_give_an_unfilled_order_its_final_status(
    parts: list[ExchangeOrder], status: OrderStatus, reason: str
) -> None:
    order = new_order()

    OUTCOME.apply(order, parts, NOW)

    assert (order.status, order.reason, order.updated_at) == (status, reason, NOW)


@pytest.mark.parametrize(
    ("parts", "final", "status", "reason"),
    [
        (
            [part(OrderStatus.UNCONFIRMED)],
            False,
            OrderStatus.UNCONFIRMED,
            "unconfirmed at Shioaji, whose record of today settles it: unconfirmed 1000",
        ),
        (
            [part(OrderStatus.SUBMITTED)],
            False,
            OrderStatus.UNCONFIRMED,
            "unconfirmed at Shioaji, whose record of today settles it: submitted 1000",
        ),
        ([part(OrderStatus.UNCONFIRMED)], True, OrderStatus.FAILED, "Shioaji never listed it by its session's end: unconfirmed 1000"),
        (
            [part(OrderStatus.SUBMITTED), part(OrderStatus.UNCONFIRMED, 500)],
            True,
            OrderStatus.CANCELLED,
            "IOC unfilled: filled 0 of 1500; submitted 1000; unconfirmed 500",
        ),
    ],
    ids=["unlisted", "still working", "never listed by the day's end", "once final a working part has ended"],
)
def test_once_its_days_record_is_final_an_order_none_of_whose_parts_the_broker_listed_fails_and_a_working_part_has_ended(
    parts: list[ExchangeOrder], final: bool, status: OrderStatus, reason: str
) -> None:
    order = new_order()
    order.leave_unconfirmed("the broker's answer was lost", now=NOW)

    OUTCOME.apply(order, parts, NOW, final=final)

    assert (order.status, order.reason) == (status, reason)


def test_an_order_of_an_earlier_session_fails_with_what_it_recorded_and_the_tags_of_its_parts_to_look_for() -> None:
    sent = new_order(quantity=1430)
    sent.submit(now=NOW)
    sent.fill(1000, 100.0, 143, 0, now=NOW)
    sent.leave_unconfirmed("the odd-lot part's answer was lost", now=NOW)
    rule, monday, friday = PastSessionRule(lot_split_rule=LotSplitRule(board_lot_shares=1000)), date(2026, 10, 19), date(2026, 10, 16)

    tag = sent.id.hex[:5]
    assert rule.apply(sent, ExecutionProvider.SHIOAJI, monday, monday) is None
    assert rule.apply(sent, ExecutionProvider.SHIOAJI, friday, monday) == (
        f"SinoPac no longer lists the orders of 2026-10-16, so what the parts tagged {tag}0, {tag}1 did there cannot be "
        "read: check SinoPac's order history; 1000 of 1430 shares were recorded filled"
    )


def test_a_partly_filled_order_is_cancelled_with_what_filled() -> None:
    order = new_order()
    order.submit(now=NOW)
    cost = COSTS.apply(TradeAction.BUY, "2330", 100, 1000, now=NOW)
    order.fill(1000, 100, cost.fee, cost.tax, now=NOW)

    OUTCOME.apply(order, [part(OrderStatus.FILLED, dealt=1000), part(OrderStatus.REJECTED, 500)], NOW)

    assert (order.status, order.filled_quantity, order.reason) == (
        OrderStatus.CANCELLED,
        1000,
        "IOC unfilled: filled 1000 of 1500; filled 1000; rejected 500",
    )


SIMULATION_CASH = SimulationCashRule(simulation_initial_cash=1_000_000)


def held(stock_id: str, quantity: int, average_cost: float) -> Position:
    return Position(stock_id=stock_id, quantity=quantity, average_cost=average_cost)


def sold(realized_pnl: float) -> BrokerFill:
    return BrokerFill(
        stock_id="2317", action=TradeAction.SELL, quantity=1000, price=58.0, filled_on=date(2026, 10, 9), realized_pnl=realized_pnl
    )


@pytest.mark.parametrize(
    ("positions", "held_yesterday", "bought_today", "sales", "cash"),
    [
        ([], {}, {}, [], 1_000_000),
        ([held("2330", 1000, 100.0), held("2603", 2000, 50.0)], {"2330": 1000, "2603": 2000}, {}, [], 800_000),
        ([held("2330", 1000, 100.0)], {"2330": 1000}, {}, [sold(-2_300.0), sold(5_000.0)], 902_700),
        ([], {}, {}, [sold(-2_300.0)], 997_700),
        ([held("2330", 1000, 100.0)], {}, {"2330": 100_142.0}, [], 899_858),
        ([held("2330", 1000, 100.0)], {}, {"2330": 150_213.0}, [], 849_787),
        ([held("2330", 3000, 100.0)], {"2330": 2000}, {"2330": 100_142.0}, [], 700_000),
        ([held("2330", 3000, 100.0)], {"2330": 3000}, {"2330": 100_142.0}, [], 599_858),
        ([held("2603", 2000, 50.0)], {"2603": 2000}, {"2330": 100_142.0}, [], 799_858),
        ([held("2330", 600, 100.0), held("2330", 400, 100.0)], {"2330": 1000}, {"2330": 100_142.0}, [], 799_858),
        ([held("2330", 11_000, 100.0)], {"2330": 11_000}, {}, [], -100_000),
    ],
    ids=[
        "an account that never traded has the starting cash",
        "what the open positions cost is spent",
        "the profit and loss of the sales is added",
        "a stock sold whole leaves its profit or loss",
        "a stock bought new today whose position lists the BUY counts it once",
        "a stock bought new today whose position lists part of the BUYs counts them whole",
        "a stock held since yesterday whose position lists today's BUY counts it once",
        "a stock held since yesterday whose position does not list today's BUY yet counts both",
        "a BUY of a stock the positions do not list yet still counts",
        "two rows of one stock are one position",
        "records that spent more than the starting cash give a figure below zero",
    ],
)
def test_the_simulation_cash_is_the_starting_cash_less_what_the_stocks_cost_plus_what_the_sales_realized(
    positions: list[Position], held_yesterday: dict[str, int], bought_today: dict[str, float], sales: list[BrokerFill], cash: float
) -> None:
    assert SIMULATION_CASH.apply(positions, held_yesterday, bought_today, sales) == cash
