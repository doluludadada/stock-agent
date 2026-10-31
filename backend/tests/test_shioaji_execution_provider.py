from datetime import UTC, datetime

import pytest
from shioaji.constant import Action, OrderType as BrokerTimeInForce, Status, StockOrderCond, StockOrderLot, StockPriceType, Unit
from shioaji.error import TimeoutError as ShioajiTimeoutError, TokenError
from shioaji.position import AccountBalance
from support.fake_shioaji import FakeShioaji, Report, position
from trading_stack import SilentLogger

from a_domain.model.trading.order import Order
from a_domain.types.enums import OrderStatus, OrderType, TimeInForce, TradeAction
from a_domain.types.ids import new_decision_id, new_run_id
from b_application.config.app_config import AppConfig
from b_application.config.trading_config import ShioajiConfig
from c_infrastructure.trading.shioaji.execution_provider import ORDER_STATUS, ShioajiExecutionProvider

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)

pytestmark = pytest.mark.asyncio

CONFIG = AppConfig(project_root=".")
COSTS = CONFIG.market.cost_rule()


def provider(client: FakeShioaji) -> ShioajiExecutionProvider:
    if client.stock_account is None:
        client.stock_account = client.account_at_login

    return unconnected(client, simulation=True)


def unconnected(client: FakeShioaji, simulation: bool) -> ShioajiExecutionProvider:
    """An adapter whose client has not logged in yet: connect() logs it in."""
    config = CONFIG.model_copy(update={"shioaji": credentials(simulation)})

    return ShioajiExecutionProvider(client=client, config=config, logger=SilentLogger())


def order(
    action: TradeAction = TradeAction.BUY,
    quantity: int = 1000,
    price: float | None = 100.0,
    time_in_force: TimeInForce = TimeInForce.IOC,
    stock_id: str = "2330",
) -> Order:
    return Order(
        run_id=new_run_id(),
        decision_id=new_decision_id(),
        stock_id=stock_id,
        action=action,
        order_type=OrderType.LIMIT if price is not None else OrderType.MARKET,
        quantity=quantity,
        limit_price=price,
        time_in_force=time_in_force,
        created_at=NOW,
        updated_at=NOW,
    )


def sent(client: FakeShioaji) -> list[tuple]:
    return [(trade.order.order_lot, trade.order.quantity, trade.order.order_type, trade.order.price) for trade in client.placed]


def credentials(simulation: bool) -> ShioajiConfig:
    return ShioajiConfig(
        simulation=simulation,
        poll_interval_seconds=0,
        max_polls=3,
        SHIOAJI_API_KEY="key",
        SHIOAJI_SECRET_KEY="secret",
        SHIOAJI_CA_PATH="/certs/Sinopac.pfx",
        SHIOAJI_CA_PASSWORD="ca-password",
        SHIOAJI_PERSON_ID="A123456789",
    )


async def test_a_whole_lot_buy_is_one_board_lot_limit_order_on_the_logged_in_account() -> None:
    client = FakeShioaji()
    placing = order(quantity=2000, price=101.5)

    placed = await provider(client).place_order(placing)

    [trade] = client.placed
    broker_order = trade.order
    assert (broker_order.action, broker_order.price, broker_order.quantity, broker_order.price_type) == (
        Action.Buy,
        101.5,
        2,
        StockPriceType.LMT,
    )
    assert (broker_order.order_type, broker_order.order_lot, broker_order.order_cond) == (
        BrokerTimeInForce.IOC,
        StockOrderLot.Common,
        StockOrderCond.Cash,
    )
    assert (broker_order.account, broker_order.custom_field) == (client.stock_account, f"{placing.id.hex[:5]}0")
    assert (placed.status, placed.filled_quantity, placed.average_filled_price) == (OrderStatus.FILLED, 2000, 101.5)
    cost = COSTS.apply(TradeAction.BUY, "2330", 101.5, 2000, now=NOW)
    assert (placed.fee, placed.tax) == (cost.fee, cost.tax)


async def test_fewer_than_1000_shares_are_one_intraday_odd_lot_rod_order_in_shares() -> None:
    client = FakeShioaji(holdings=[position("2330", 500, 90.0)])

    placed = await provider(client).place_order(order(TradeAction.SELL, quantity=500, price=99.0))

    assert sent(client) == [(StockOrderLot.IntradayOdd, 500, BrokerTimeInForce.ROD, 99.0)]
    assert client.placed[0].order.action == Action.Sell
    cost = COSTS.apply(TradeAction.SELL, "2330", 99.0, 500, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.tax) == (OrderStatus.FILLED, 500, cost.tax)
    assert placed.realized_pnl == pytest.approx(cost.net - 500 * 90.0)


async def test_a_mixed_quantity_is_split_into_a_board_lot_ioc_order_and_an_odd_lot_rod_order() -> None:
    client = FakeShioaji()
    placing = order(quantity=2500, price=100.0)

    placed = await provider(client).place_order(placing)

    assert sent(client) == [
        (StockOrderLot.Common, 2, BrokerTimeInForce.IOC, 100.0),
        (StockOrderLot.IntradayOdd, 500, BrokerTimeInForce.ROD, 100.0),
    ]
    assert [trade.order.custom_field for trade in client.placed] == [f"{placing.id.hex[:5]}0", f"{placing.id.hex[:5]}1"]
    lots, odd = COSTS.apply(TradeAction.BUY, "2330", 100.0, 2000, now=NOW), COSTS.apply(TradeAction.BUY, "2330", 100.0, 500, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.fee) == (OrderStatus.FILLED, 2500, lots.fee + odd.fee)


async def test_fok_is_sent_as_fok() -> None:
    client = FakeShioaji()

    placed = await provider(client).place_order(order(time_in_force=TimeInForce.FOK))

    assert (sent(client), placed.status) == ([(StockOrderLot.Common, 1, BrokerTimeInForce.FOK, 100.0)], OrderStatus.FILLED)


@pytest.mark.parametrize(
    ("placing", "reason"),
    [
        (order(time_in_force=TimeInForce.ROD), "UNSUPPORTED_TIME_IN_FORCE: ROD would leave a working order"),
        (order(quantity=1500, time_in_force=TimeInForce.FOK), "UNSUPPORTED_TIME_IN_FORCE: FOK cannot cover 1500 shares"),
        (order(quantity=500, time_in_force=TimeInForce.FOK), "UNSUPPORTED_TIME_IN_FORCE: FOK cannot cover 500 shares"),
        (order(price=None), "UNSUPPORTED_ORDER_TYPE"),
        (order(stock_id="9999"), "BROKER_REFUSED: Shioaji has no stock contract 9999"),
        (order(TradeAction.SELL), "POSITION_NOT_FOUND"),
    ],
)
async def test_an_order_the_adapter_cannot_send_faithfully_is_rejected_and_never_sent(placing: Order, reason: str) -> None:
    client = FakeShioaji()

    placed = await provider(client).place_order(placing)

    assert (placed.status, client.placed) == (OrderStatus.REJECTED, [])
    assert placed.reason is not None and placed.reason.startswith(reason)


async def test_a_buy_is_refused_when_cash_minus_settlement_payments_due_cannot_pay_it() -> None:
    client = FakeShioaji(settlement_amounts=(0.0, 50_000.0, -950_000.0))

    placed = await provider(client).place_order(order(quantity=1000, price=100.0))

    assert (placed.status, client.placed) == (OrderStatus.REJECTED, [])
    assert placed.reason == "INSUFFICIENT_CASH: needs 100,142 including fee, cash is 50,000"


async def test_selling_more_than_the_broker_holds_is_refused() -> None:
    client = FakeShioaji(holdings=[position("2330", 1000, 90.0)])

    placed = await provider(client).place_order(order(TradeAction.SELL, quantity=2000))

    assert (placed.status, client.placed) == (OrderStatus.REJECTED, [])
    assert placed.reason == "INSUFFICIENT_POSITION: holds 1000, selling 2000"


async def test_every_shioaji_status_has_a_domain_status() -> None:
    assert set(ORDER_STATUS) == set(Status)


@pytest.mark.parametrize(
    ("report", "status", "filled", "reason"),
    [
        (Report(Status.Filled, ((99.5, 1),)), OrderStatus.FILLED, 1000, None),
        (
            Report(Status.Cancelled),
            OrderStatus.CANCELLED,
            0,
            "IOC unfilled: filled 0 of 1000; Common 1 lots IOC Cancelled, dealt 0 shares",
        ),
        (
            Report(Status.Failed, msg="price out of range"),
            OrderStatus.REJECTED,
            0,
            "BROKER_REFUSED: Common 1 lots IOC Failed, dealt 0 shares (price out of range)",
        ),
        (Report(Status.Inactive), OrderStatus.FAILED, 0, "unexplained broker result: Common 1 lots IOC Inactive, dealt 0 shares"),
    ],
)
async def test_each_final_shioaji_status_ends_the_domain_order(
    report: Report, status: OrderStatus, filled: int, reason: str | None
) -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.Submitted), report]})

    placed = await provider(client).place_order(order())

    assert (placed.status, placed.filled_quantity, placed.reason, client.cancelled) == (status, filled, reason, [])


@pytest.mark.parametrize("working", [Status.PendingSubmit, Status.PreSubmitted, Status.Submitted, Status.PartFilled])
async def test_an_order_still_working_after_the_polls_is_cancelled(working: Status) -> None:
    deals = ((100.0, 1),) if working == Status.PartFilled else ()
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(working, deals)]})

    placed = await provider(client).place_order(order(quantity=2000))

    assert client.cancelled == client.placed
    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 1000 if deals else 0)
    assert placed.reason is not None and placed.reason.startswith(f"IOC unfilled: filled {1000 if deals else 0} of 2000")


async def test_a_partial_fill_is_recorded_before_the_ioc_remainder_is_cancelled() -> None:
    client = FakeShioaji(
        scripts={StockOrderLot.Common: [Report(Status.PartFilled, ((100.0, 1),)), Report(Status.Cancelled, ((100.0, 1),))]}
    )

    placed = await provider(client).place_order(order(quantity=3000))

    cost = COSTS.apply(TradeAction.BUY, "2330", 100.0, 1000, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.fee, client.cancelled) == (OrderStatus.CANCELLED, 1000, cost.fee, [])


async def test_an_order_still_working_after_the_cancel_fails_and_says_to_check_the_broker() -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.PartFilled, ((100.0, 1),))]}, honours_cancel=False)

    placed = await provider(client).place_order(order(quantity=2000))

    assert (placed.status, placed.filled_quantity, client.cancelled) == (OrderStatus.FAILED, 1000, client.placed)
    assert placed.reason is not None and placed.reason.startswith("still working at the broker after a cancel request, check Shioaji")


async def test_filled_without_deals_for_the_whole_quantity_fails_instead_of_guessing() -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.Filled, ((100.0, 1),))]})

    placed = await provider(client).place_order(order(quantity=2000))

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FAILED, 1000)


async def test_deals_at_several_prices_fill_at_their_volume_weighted_price() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Filled, ((10.05, 300), (10.05, 300), (10.0, 399)))]})

    placed = await provider(client).place_order(order(quantity=999, price=10.05))

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FILLED, 999)
    assert placed.average_filled_price == pytest.approx((10.05 * 600 + 10.0 * 399) / 999)


async def test_deals_at_the_limit_price_fill_even_where_their_float_average_rounds_above_it() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Filled, ((10.8, 1), (10.8, 1), (10.8, 1)))]})

    placed = await provider(client).place_order(order(quantity=3, price=10.8))

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FILLED, 3)
    assert placed.average_filled_price == pytest.approx(10.8)


async def test_when_the_odd_lot_part_is_refused_the_board_lot_fill_stands_and_the_order_is_cancelled() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Failed, msg="price out of range")]})

    placed = await provider(client).place_order(order(quantity=1500))

    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 1000)
    assert placed.reason is not None and "IntradayOdd 500 shares ROD Failed, dealt 0 shares (price out of range)" in placed.reason


async def test_an_odd_lot_rod_part_still_working_after_the_polls_is_cancelled_and_the_order_says_so() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Submitted)]})

    placed = await provider(client).place_order(order(quantity=1500))

    [board_lot, odd_lot] = client.placed
    assert client.cancelled == [odd_lot]
    assert (odd_lot.order.order_type, odd_lot.status.status) == (BrokerTimeInForce.ROD, Status.Cancelled)
    cost = COSTS.apply(TradeAction.BUY, "2330", 100.0, 1000, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.fee) == (OrderStatus.CANCELLED, 1000, cost.fee)
    assert placed.reason == (
        "IOC unfilled: filled 1000 of 1500; Common 1 lots IOC Filled, dealt 1000 shares; "
        "IntradayOdd 500 shares ROD Cancelled, dealt 0 shares"
    )


async def test_an_odd_lot_rod_part_partly_dealt_before_its_cancel_records_what_it_dealt() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.PartFilled, ((100.0, 200),))]})

    placed = await provider(client).place_order(order(quantity=1500))

    lots, odd = COSTS.apply(TradeAction.BUY, "2330", 100.0, 1000, now=NOW), COSTS.apply(TradeAction.BUY, "2330", 100.0, 200, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.fee) == (OrderStatus.CANCELLED, 1200, lots.fee + odd.fee)
    assert placed.reason is not None and placed.reason.endswith("IntradayOdd 500 shares ROD Cancelled, dealt 200 shares")


async def test_an_odd_lot_rod_part_the_broker_keeps_working_after_the_cancel_fails_the_order() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Submitted)]}, honours_cancel=False)

    placed = await provider(client).place_order(order(quantity=500))

    assert (placed.status, placed.filled_quantity, client.cancelled) == (OrderStatus.FAILED, 0, client.placed)
    assert placed.reason == (
        "still working at the broker after a cancel request, check Shioaji: IntradayOdd 500 shares ROD Submitted, dealt 0 shares"
    )


async def test_when_every_part_is_refused_the_order_is_rejected_by_the_broker() -> None:
    client = FakeShioaji(scripts={lot: [Report(Status.Failed, msg="closing auction")] for lot in StockOrderLot})

    placed = await provider(client).place_order(order(quantity=1500))

    assert (placed.status, placed.filled_quantity, len(client.placed)) == (OrderStatus.REJECTED, 0, 2)
    assert placed.reason is not None and placed.reason.startswith("BROKER_REFUSED: Common 1 lots IOC Failed")


async def test_a_timed_out_place_order_is_found_by_its_tag_and_settled() -> None:
    client = FakeShioaji(place_error=ShioajiTimeoutError("place_order", {}), place_error_after_accepting=True)

    placed = await provider(client).place_order(order())

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FILLED, 1000)


async def test_an_unconfirmed_order_fails_and_says_it_may_have_reached_the_exchange() -> None:
    client = FakeShioaji(place_error=ShioajiTimeoutError("place_order", {}))

    placed = await provider(client).place_order(order())

    assert placed.status == OrderStatus.FAILED
    assert placed.reason is not None and "may have reached the exchange" in placed.reason


async def test_get_account_reads_cash_less_payments_due_and_the_long_cash_positions_in_shares() -> None:
    client = FakeShioaji(
        settlement_amounts=(-10_000.0, 20_000.0, -30_000.0),
        holdings=[
            position("2330", 1500, 95.5),
            position("2603", 2000, 50.0, cond=StockOrderCond.MarginTrading),
            position("2317", 1000, 120.0, direction=Action.Sell, cond=StockOrderCond.ShortSelling),
            position("2454", 1000, 900.0, direction=Action.Sell),
            position("6505", 50, 0.0),
        ],
    )

    account = await provider(client).get_account()

    assert (account.account_id, account.cash) == ("0012345", 1_000_000 - 10_000 - 30_000)
    assert [(held.stock_id, held.quantity, held.average_cost) for held in account.positions] == [("2330", 1500, 95.5)]
    assert client.position_units == [Unit.Share]


async def test_get_account_refuses_a_balance_the_broker_reports_as_an_error() -> None:
    client = FakeShioaji()
    client.balance = client.balance.model_copy(update={"errmsg": "bank link down"})

    with pytest.raises(RuntimeError, match="bank link down"):
        await provider(client).get_account()


async def test_simulation_login_uses_the_api_key_pair_and_no_ca() -> None:
    client = FakeShioaji()

    await unconnected(client, simulation=True).connect()

    assert ([(login["api_key"], login["secret_key"]) for login in client.logins], client.ca_activations) == ([("key", "secret")], [])
    assert client.stock_account is client.account_at_login


async def test_production_login_activates_the_ca() -> None:
    client = FakeShioaji(simulation=False)

    await unconnected(client, simulation=False).connect()

    assert client.ca_activations == [{"ca_path": "/certs/Sinopac.pfx", "ca_passwd": "ca-password", "person_id": "A123456789"}]


@pytest.mark.parametrize(
    ("client", "message"),
    [
        (FakeShioaji(simulation=False, login_error=TokenError(401, "bad key")), "bad key"),
        (FakeShioaji(simulation=False, account_at_login=None), "no stock account"),
        (FakeShioaji(simulation=False, ca_activates=False), "CA certificate at /certs/Sinopac.pfx was not activated"),
        (FakeShioaji(simulation=False, ca_error=ValueError("wrong CA password")), "wrong CA password"),
    ],
)
async def test_a_failed_login_or_ca_activation_raises_saying_what_failed(client: FakeShioaji, message: str) -> None:
    with pytest.raises(Exception, match=message):
        await unconnected(client, simulation=False).connect()


async def test_production_refuses_an_account_that_has_not_signed_the_api_agreement() -> None:
    client = FakeShioaji(simulation=False)
    client.account_at_login = client.account_at_login.model_copy(update={"signed": False})

    with pytest.raises(RuntimeError, match="has not signed"):
        await unconnected(client, simulation=False).connect()


async def test_a_second_buy_is_refused_when_todays_first_fill_used_the_cash() -> None:
    client = FakeShioaji(balance=AccountBalance(acc_balance=150_000.0, date="2026-10-19", errmsg=""))
    broker = provider(client)

    first = await broker.place_order(order(quantity=1000, price=100.0))
    second = await broker.place_order(order(quantity=1000, price=100.0))

    assert (first.status, second.status, len(client.placed)) == (OrderStatus.FILLED, OrderStatus.REJECTED, 1)
    assert second.reason == "INSUFFICIENT_CASH: needs 100,142 including fee, cash is 49,858"


async def test_fills_and_cancels_are_read_back_from_the_trade_list_when_place_order_returned_a_copy() -> None:
    client = FakeShioaji(
        scripts={StockOrderLot.Common: [Report(Status.Submitted), Report(Status.PartFilled, ((100.0, 1),))]}, updates_in_place=False
    )

    placed = await provider(client).place_order(order(quantity=2000))

    assert (placed.status, placed.filled_quantity, len(client.cancelled)) == (OrderStatus.CANCELLED, 1000, 1)


async def test_an_order_whose_deals_lag_its_dealt_quantity_fails_instead_of_under_recording() -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.Cancelled, ((100.0, 1),), deal_quantity=2)]})

    placed = await provider(client).place_order(order(quantity=3000))

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FAILED, 1000)
    assert placed.reason is not None and placed.reason.startswith("unexplained broker result")
