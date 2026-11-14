import asyncio
import traceback
from datetime import UTC, date, datetime

import pytest
import shioaji
from shioaji.constant import Action, OrderType as BrokerTimeInForce, Status, StockOrderCond, StockOrderLot, StockPriceType, Unit
from shioaji.error import TimeoutError as ShioajiTimeoutError, TokenError
from shioaji.position import AccountBalance
from support.fake_shioaji import FakeShioaji, Report, position, sale
from support.fakes import RecordingLogger, no_refusal
from support.settings import environment_setup, shipped_config
from trading_stack import SilentLogger

from a_domain.model.trading.order import Order
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import OrderStatus, OrderType, RejectReason, SystemEnvironment, TimeInForce, TradeAction
from a_domain.types.ids import new_decision_id, new_run_id
from b_application.config.trading_config import ShioajiConfig, ShioajiLogin
from c_infrastructure.market.shioaji_quote_provider import ShioajiConnection, ShioajiQuoteProvider
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from c_infrastructure.system.market_clock import TaiwanMarketClock
from c_infrastructure.trading.shioaji.execution_provider import ORDER_STATUS, ShioajiExecutionProvider
from d_presentation.dependencies import ProcessState, connect_shioaji

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)

pytestmark = pytest.mark.asyncio

CONFIG = shipped_config()
COSTS = CONFIG.market.cost_rule()


def provider(client: FakeShioaji) -> ShioajiExecutionProvider:
    if client.stock_account is None:
        client.stock_account = client.account_at_login

    login, connection = login_of(simulation=True), ShioajiConnection(client=client, up=True)
    return ShioajiExecutionProvider(
        connection=connection, quotes=quotes_of(connection, login), login=login, config=CONFIG, logger=SilentLogger()
    )


def login_of(simulation: bool) -> ShioajiLogin:
    login = credentials().login(SystemEnvironment.TEST if simulation else SystemEnvironment.PROD)
    assert login is not None
    return login


async def connected(client: FakeShioaji, simulation: bool) -> ShioajiExecutionProvider:
    """
    The broker on a client the quote provider logged in, to simulation as test does or production as prod does, once
    its connect() checked the login: the startup's order.
    """
    login, connection = login_of(simulation), ShioajiConnection(client=client)
    quotes = quotes_of(connection, login)
    broker = ShioajiExecutionProvider(connection=connection, quotes=quotes, login=login, config=CONFIG, logger=SilentLogger())
    await quotes.connect()
    await broker.connect()
    return broker


def quotes_of(connection: ShioajiConnection, login: ShioajiLogin) -> ShioajiQuoteProvider:
    return ShioajiQuoteProvider(
        connection=connection,
        new_client=FakeShioaji,
        login=login,
        market_clock=TaiwanMarketClock(CONFIG.market_hours),
        market_data=CONFIG.market_data,
        board_lot_shares=1000,
        logger=SilentLogger(),
    )


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


def credentials() -> ShioajiConfig:
    """Every Shioaji variable set, the test pair to its own values: a login shows which pair its environment read."""
    return ShioajiConfig(
        _env_file=None,
        poll_interval_seconds=0,
        max_polls=3,
        SHIOAJI_API_KEY="key",
        SHIOAJI_SECRET_KEY="secret",
        SHIOAJI_CA_PATH="/certs/Sinopac.pfx",
        SHIOAJI_CA_PASSWORD="ca-password",
        SHIOAJI_PERSON_ID="A123456789",
        SHIOAJI_API_KEY_TEST="test-key",
        SHIOAJI_SECRET_KEY_TEST="test-secret",
    )


async def test_a_whole_lot_buy_is_one_board_lot_limit_order_on_the_logged_in_account() -> None:
    client = FakeShioaji()
    placing = order(quantity=2000, price=101.5)

    placed = await provider(client).place_order(placing, no_refusal)

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

    placed = await provider(client).place_order(order(TradeAction.SELL, quantity=500, price=99.0), no_refusal)

    assert sent(client) == [(StockOrderLot.IntradayOdd, 500, BrokerTimeInForce.ROD, 99.0)]
    assert client.placed[0].order.action == Action.Sell
    cost = COSTS.apply(TradeAction.SELL, "2330", 99.0, 500, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.tax) == (OrderStatus.FILLED, 500, cost.tax)
    assert placed.realized_pnl == pytest.approx(cost.net - 500 * 90.0)


async def test_a_mixed_quantity_is_split_into_a_board_lot_ioc_order_and_an_odd_lot_rod_order() -> None:
    client = FakeShioaji()
    placing = order(quantity=2500, price=100.0)

    placed = await provider(client).place_order(placing, no_refusal)

    assert sent(client) == [
        (StockOrderLot.Common, 2, BrokerTimeInForce.IOC, 100.0),
        (StockOrderLot.IntradayOdd, 500, BrokerTimeInForce.ROD, 100.0),
    ]
    assert [trade.order.custom_field for trade in client.placed] == [f"{placing.id.hex[:5]}0", f"{placing.id.hex[:5]}1"]
    lots, odd = COSTS.apply(TradeAction.BUY, "2330", 100.0, 2000, now=NOW), COSTS.apply(TradeAction.BUY, "2330", 100.0, 500, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.fee) == (OrderStatus.FILLED, 2500, lots.fee + odd.fee)


async def test_fok_is_sent_as_fok() -> None:
    client = FakeShioaji()

    placed = await provider(client).place_order(order(time_in_force=TimeInForce.FOK), no_refusal)

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

    placed = await provider(client).place_order(placing, no_refusal)

    assert (placed.status, client.placed) == (OrderStatus.REJECTED, [])
    assert placed.reason is not None and placed.reason.startswith(reason)


async def test_a_buy_is_refused_when_cash_minus_settlement_payments_due_cannot_pay_it() -> None:
    client = FakeShioaji(settlement_amounts=(0.0, 50_000.0, -950_000.0))

    placed = await provider(client).place_order(order(quantity=1000, price=100.0), no_refusal)

    assert (placed.status, client.placed) == (OrderStatus.REJECTED, [])
    assert placed.reason == "INSUFFICIENT_CASH: needs 100,142 including fee, cash is 50,000"


async def test_selling_more_than_the_broker_holds_is_refused() -> None:
    client = FakeShioaji(holdings=[position("2330", 1000, 90.0)])

    placed = await provider(client).place_order(order(TradeAction.SELL, quantity=2000), no_refusal)

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
            Report(Status.Failed, msg="price out of range", status_code="88"),
            OrderStatus.REJECTED,
            0,
            "BROKER_REFUSED: Common 1 lots IOC Failed, dealt 0 shares (status 88)",
        ),
        (Report(Status.Inactive), OrderStatus.FAILED, 0, "unexplained broker result: Common 1 lots IOC Inactive, dealt 0 shares"),
    ],
)
async def test_each_final_shioaji_status_ends_the_domain_order(
    report: Report, status: OrderStatus, filled: int, reason: str | None
) -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.Submitted), report]})

    placed = await provider(client).place_order(order(), no_refusal)

    assert (placed.status, placed.filled_quantity, placed.reason, client.cancelled) == (status, filled, reason, [])


@pytest.mark.parametrize("working", [Status.PendingSubmit, Status.PreSubmitted, Status.Submitted, Status.PartFilled])
async def test_an_order_still_working_after_the_polls_is_cancelled(working: Status) -> None:
    deals = ((100.0, 1),) if working == Status.PartFilled else ()
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(working, deals)]})

    placed = await provider(client).place_order(order(quantity=2000), no_refusal)

    assert client.cancelled == client.placed
    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 1000 if deals else 0)
    assert placed.reason is not None and placed.reason.startswith(f"IOC unfilled: filled {1000 if deals else 0} of 2000")


async def test_a_partial_fill_is_recorded_before_the_ioc_remainder_is_cancelled() -> None:
    client = FakeShioaji(
        scripts={StockOrderLot.Common: [Report(Status.PartFilled, ((100.0, 1),)), Report(Status.Cancelled, ((100.0, 1),))]}
    )

    placed = await provider(client).place_order(order(quantity=3000), no_refusal)

    cost = COSTS.apply(TradeAction.BUY, "2330", 100.0, 1000, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.fee, client.cancelled) == (OrderStatus.CANCELLED, 1000, cost.fee, [])


async def test_an_order_still_working_after_the_cancel_fails_and_says_to_check_the_broker() -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.PartFilled, ((100.0, 1),))]}, honours_cancel=False)

    placed = await provider(client).place_order(order(quantity=2000), no_refusal)

    assert (placed.status, placed.filled_quantity, client.cancelled) == (OrderStatus.FAILED, 1000, client.placed)
    assert placed.reason is not None and placed.reason.startswith("still working at the broker after a cancel request, check Shioaji")


async def test_filled_without_deals_for_the_whole_quantity_fails_instead_of_guessing() -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.Filled, ((100.0, 1),))]})

    placed = await provider(client).place_order(order(quantity=2000), no_refusal)

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FAILED, 1000)


async def test_deals_at_several_prices_fill_at_their_volume_weighted_price() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Filled, ((10.05, 300), (10.05, 300), (10.0, 399)))]})

    placed = await provider(client).place_order(order(quantity=999, price=10.05), no_refusal)

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FILLED, 999)
    assert placed.average_filled_price == pytest.approx((10.05 * 600 + 10.0 * 399) / 999)


async def test_deals_at_the_limit_price_fill_even_where_their_float_average_rounds_above_it() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Filled, ((10.8, 1), (10.8, 1), (10.8, 1)))]})

    placed = await provider(client).place_order(order(quantity=3, price=10.8), no_refusal)

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FILLED, 3)
    assert placed.average_filled_price == pytest.approx(10.8)


async def test_when_the_odd_lot_part_is_refused_the_board_lot_fill_stands_and_the_order_is_cancelled() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Failed, msg="price out of range", status_code="88")]})

    placed = await provider(client).place_order(order(quantity=1500), no_refusal)

    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 1000)
    assert placed.reason is not None and "IntradayOdd 500 shares ROD Failed, dealt 0 shares (status 88)" in placed.reason


async def test_an_odd_lot_rod_part_still_working_after_the_polls_is_cancelled_and_the_order_says_so() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Submitted)]})

    placed = await provider(client).place_order(order(quantity=1500), no_refusal)

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

    placed = await provider(client).place_order(order(quantity=1500), no_refusal)

    lots, odd = COSTS.apply(TradeAction.BUY, "2330", 100.0, 1000, now=NOW), COSTS.apply(TradeAction.BUY, "2330", 100.0, 200, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.fee) == (OrderStatus.CANCELLED, 1200, lots.fee + odd.fee)
    assert placed.reason is not None and placed.reason.endswith("IntradayOdd 500 shares ROD Cancelled, dealt 200 shares")


async def test_an_odd_lot_rod_part_the_broker_keeps_working_after_the_cancel_fails_the_order() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Submitted)]}, honours_cancel=False)

    placed = await provider(client).place_order(order(quantity=500), no_refusal)

    assert (placed.status, placed.filled_quantity, client.cancelled) == (OrderStatus.FAILED, 0, client.placed)
    assert placed.reason == (
        "still working at the broker after a cancel request, check Shioaji: IntradayOdd 500 shares ROD Submitted, dealt 0 shares"
    )


async def test_when_every_part_is_refused_the_order_is_rejected_by_the_broker() -> None:
    client = FakeShioaji(scripts={lot: [Report(Status.Failed, msg="closing auction")] for lot in StockOrderLot})

    placed = await provider(client).place_order(order(quantity=1500), no_refusal)

    assert (placed.status, placed.filled_quantity, len(client.placed)) == (OrderStatus.REJECTED, 0, 2)
    assert placed.reason is not None and placed.reason.startswith("BROKER_REFUSED: Common 1 lots IOC Failed")


async def test_a_timed_out_place_order_is_found_by_its_tag_and_settled() -> None:
    client = FakeShioaji(place_error=ShioajiTimeoutError("place_order", {}), place_error_after_accepting=True)

    placed = await provider(client).place_order(order(), no_refusal)

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FILLED, 1000)


async def test_an_unconfirmed_order_fails_and_says_it_may_have_reached_the_exchange() -> None:
    client = FakeShioaji(place_error=ShioajiTimeoutError("place_order", {}))

    placed = await provider(client).place_order(order(), no_refusal)

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

    with pytest.raises(RuntimeError, match="^Shioaji answered the account balance with an error message$"):
        await provider(client).get_account()


async def test_the_statement_is_the_account_as_the_broker_reports_it_and_sends_nothing() -> None:
    client = FakeShioaji(
        settlement_amounts=(-10_000.0, 0.0, 20_000.0),
        holdings=[
            position("2330", 1500, 95.5).model_copy(update={"last_price": 104.0, "pnl": 12_345.0}),
            position("2603", 2000, 50.0, cond=StockOrderCond.MarginTrading),
            position("6505", 37, 80.0).model_copy(update={"last_price": 0.0}),
        ],
        profit_losses=[sale("2317", 1000, 58.0, -2_300.0, "2026-10-09"), sale("1101", 37, 35.0, 10.0, "2025-09-01")],
    )
    broker = provider(client)
    await broker.place_order(order(quantity=1500), no_refusal)
    sent = list(client.placed)

    statement = await broker.statement(date(2026, 7, 21), date(2026, 10, 19))

    assert (statement.simulation, statement.balance, statement.sales_from) == (True, 1_000_000, date(2026, 7, 21))
    assert [(settlement.settles_on, settlement.amount) for settlement in statement.settlements] == [
        (date(2026, 10, 19), -10_000),
        (date(2026, 10, 20), 0),
        (date(2026, 10, 21), 20_000),
    ]
    assert [
        (held.stock_id, held.quantity, held.average_cost, held.mark and (held.mark.price, held.mark.unrealized_pnl))
        for held in statement.positions
    ] == [("2330", 1500, 95.5, (104.0, 12_345.0)), ("6505", 37, 80.0, None)]
    assert (statement.market_value, statement.unrealized_pnl) == (1500 * 104.0 + 37 * 80.0, 12_345.0)
    assert [(fill.stock_id, fill.action, fill.quantity, fill.price, fill.filled_on) for fill in statement.fills] == [
        ("2330", TradeAction.BUY, 1000, 100.0, date(2026, 10, 19)),
        ("2330", TradeAction.BUY, 500, 100.0, date(2026, 10, 19)),
    ]
    assert [(sold.stock_id, sold.quantity, sold.price, sold.filled_on, sold.realized_pnl) for sold in statement.sales] == [
        ("2317", 1000, 58.0, date(2026, 10, 9), -2_300.0)
    ]
    assert (statement.realized_pnl, client.profit_loss_requests) == (-2_300.0, [("2026-07-21", "2026-10-19", Unit.Share)])
    assert (client.placed, client.cancelled) == (sent, [])
    assert private_parts(repr(statement)) == []


async def test_the_days_fills_count_shares_for_every_lot_the_holder_traded_elsewhere_and_leave_out_a_block_trade() -> None:
    client = FakeShioaji()
    broker = provider(client)
    assert set(StockOrderLot) == {lot for lot, _ in ELSEWHERE}, "the SDK has a lot this test does not place"

    for lot, quantity in ELSEWHERE:
        client.place_order(
            client.Contracts.Stocks["2330"],
            shioaji.Order(
                price=100.0,
                quantity=quantity,
                action=Action.Buy,
                price_type=StockPriceType.LMT,
                order_type=BrokerTimeInForce.ROD,
                order_lot=lot,
                account=client.stock_account,
            ),
        )

    fills = await broker.fills(date(2026, 10, 19))

    assert [fill.quantity for fill in fills] == [2000, 1000, 30, 7]


ELSEWHERE = (
    (StockOrderLot.Common, 2),
    (StockOrderLot.Fixing, 1),
    (StockOrderLot.Odd, 30),
    (StockOrderLot.IntradayOdd, 7),
    (StockOrderLot.BlockTrade, 500),
)
"""One order of each lot the SDK has, its quantity in that lot's units, as the account's holder places them in SinoPac's own app."""


@pytest.mark.parametrize(
    "read", ["account_balance", "settlements", "list_positions", "update_status", "list_trades", "list_profit_loss"]
)
async def test_a_refused_read_of_the_statement_says_only_the_error_type_and_status(read: str) -> None:
    client = FakeShioaji(refusals={read: sdk_refusal()})

    with pytest.raises(RuntimeError, match="^Shioaji answered TokenError, status 401$") as refused:
        await provider(client).statement(date(2026, 7, 21), date(2026, 10, 19))

    assert private_parts(raised(refused.value)) == [] and client.placed == []


async def test_the_test_environment_logs_in_to_simulation_with_only_the_test_key_pair_and_no_ca() -> None:
    client = FakeShioaji()

    await connected(client, simulation=True)

    logins = [(login["api_key"], login["secret_key"]) for login in client.logins]
    assert (logins, client.ca_activations) == ([("test-key", "test-secret")], [])
    assert client.stock_account is client.account_at_login


async def test_the_prod_environment_logs_in_with_the_production_key_pair_and_activates_the_ca() -> None:
    client = FakeShioaji(simulation=False)

    await connected(client, simulation=False)

    assert [(login["api_key"], login["secret_key"]) for login in client.logins] == [("key", "secret")]
    assert client.ca_activations == [{"ca_path": "/certs/Sinopac.pfx", "ca_passwd": "ca-password", "person_id": "A123456789"}]


@pytest.mark.parametrize(
    ("client", "message"),
    [
        (FakeShioaji(simulation=False, login_error=TokenError(401, "bad key")), "^TokenError, status 401$"),
        (FakeShioaji(simulation=False, account_at_login=None), "no stock account"),
        (FakeShioaji(simulation=False, ca_activates=False), "CA certificate at /certs/Sinopac.pfx was not activated"),
        (FakeShioaji(simulation=False, ca_error=ValueError("wrong CA password")), "^Shioaji answered ValueError$"),
    ],
)
async def test_a_failed_login_or_ca_activation_raises_saying_what_failed(client: FakeShioaji, message: str) -> None:
    with pytest.raises(Exception, match=message):
        await connected(client, simulation=False)


async def test_production_refuses_an_account_that_has_not_signed_the_api_agreement() -> None:
    client = FakeShioaji(simulation=False)
    client.account_at_login = client.account_at_login.model_copy(update={"signed": False})

    with pytest.raises(RuntimeError, match="has not signed"):
        await connected(client, simulation=False)


async def test_a_second_buy_is_refused_when_todays_first_fill_used_the_cash() -> None:
    client = FakeShioaji(balance=AccountBalance(acc_balance=150_000.0, date="2026-10-19", errmsg=""))
    broker = provider(client)

    first = await broker.place_order(order(quantity=1000, price=100.0), no_refusal)
    second = await broker.place_order(order(quantity=1000, price=100.0), no_refusal)

    assert (first.status, second.status, len(client.placed)) == (OrderStatus.FILLED, OrderStatus.REJECTED, 1)
    assert second.reason == "INSUFFICIENT_CASH: needs 100,142 including fee, cash is 49,858"


async def test_fills_and_cancels_are_read_back_from_the_trade_list_when_place_order_returned_a_copy() -> None:
    client = FakeShioaji(
        scripts={StockOrderLot.Common: [Report(Status.Submitted), Report(Status.PartFilled, ((100.0, 1),))]}, updates_in_place=False
    )

    placed = await provider(client).place_order(order(quantity=2000), no_refusal)

    assert (placed.status, placed.filled_quantity, len(client.cancelled)) == (OrderStatus.CANCELLED, 1000, 1)


async def test_an_order_whose_deals_lag_its_dealt_quantity_fails_instead_of_under_recording() -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.Cancelled, ((100.0, 1),), deal_quantity=2)]})

    placed = await provider(client).place_order(order(quantity=3000), no_refusal)

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FAILED, 1000)
    assert placed.reason is not None and placed.reason.startswith("unexplained broker result")


SERVER_WORDS = "person A123456789 signed in from 203.0.113.7 for account 0012345"
"""What a server's refusal may repeat: the login's person id, its address and the stock account's number (the fake's)."""

PRIVATE = ("A123456789", "203.0.113.7", "0012345")


def sdk_refusal() -> TokenError:
    return TokenError(401, SERVER_WORDS)


def private_parts(*texts: str | None) -> list[str]:
    return [part for part in PRIVATE if any(part in (text or "") for text in texts)]


def raised(error: BaseException) -> str:
    """What a log of the error with its traceback shows: every exception of its chain."""
    return "".join(traceback.format_exception(error))


def said(logger: RecordingLogger) -> list[str]:
    return [message for _, message in logger.records]


async def broker_of(
    client: FakeShioaji, monkeypatch: pytest.MonkeyPatch, logger: RecordingLogger, environment: SystemEnvironment
) -> IExecutionProvider | None:
    """The SinoPac broker connect_shioaji builds on `client` at the start of a personal site in `environment`, or None."""
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: client)
    polling = CONFIG.shioaji.model_copy(update={"poll_interval_seconds": 0, "max_polls": 3})
    site = environment_setup(CONFIG.model_copy(update={"shioaji": polling}), environment)
    process = ProcessState(logger=logger, attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())
    _, broker = await connect_shioaji(site, process, TaiwanMarketClock(CONFIG.market_hours))
    return broker


@pytest.mark.parametrize(
    ("client", "says"),
    [
        (FakeShioaji(simulation=False, ca_error=sdk_refusal()), "TokenError, status 401"),
        (
            FakeShioaji(simulation=False, account_at_login=FakeShioaji().account_at_login.model_copy(update={"signed": False})),
            "has not signed",
        ),
    ],
    ids=["refused CA activation", "unsigned account"],
)
async def test_a_refused_production_account_check_offers_no_sinopac_and_says_why_without_the_servers_words_or_the_account_number(
    client: FakeShioaji, says: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = RecordingLogger()

    assert await broker_of(client, monkeypatch, logger, SystemEnvironment.PROD) is None
    assert any(says in line and "SinoPac production orders unavailable" in line for line in said(logger))
    assert private_parts(*said(logger)) == []


ACCOUNT_READS = ("account_balance", "settlements", "update_status", "list_trades", "list_positions")


@pytest.mark.parametrize(
    ("client", "says"),
    [
        *[(FakeShioaji(refusals={read: sdk_refusal()}), "Shioaji answered TokenError, status 401") for read in ACCOUNT_READS],
        (FakeShioaji(balance=AccountBalance(acc_balance=1_000_000.0, date="2026-10-19", errmsg=SERVER_WORDS)), "account balance"),
    ],
    ids=[*ACCOUNT_READS, "balance with an error message"],
)
async def test_a_refused_account_read_raises_and_fails_the_order_saying_only_the_error_type_and_status(
    client: FakeShioaji, says: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = RecordingLogger()
    broker = await broker_of(client, monkeypatch, logger, SystemEnvironment.TEST)
    assert broker is not None

    with pytest.raises(Exception) as refused:
        await broker.get_account()
    failed = await broker.place_order(order(), no_refusal)

    assert (failed.status, client.placed) == (OrderStatus.FAILED, [])
    assert says in str(refused.value) and failed.reason is not None and says in failed.reason
    assert private_parts(raised(refused.value), failed.reason, *said(logger)) == []


async def test_an_unconfirmed_order_whose_lookup_failed_says_only_the_error_types_and_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeShioaji(
        place_error=sdk_refusal(),
        place_error_after_accepting=True,
        refusals={"update_status": sdk_refusal()},
        refuses_once_placed=True,
    )
    logger = RecordingLogger()

    failed = await (await broker_of(client, monkeypatch, logger, SystemEnvironment.TEST)).place_order(order(), no_refusal)

    assert failed.status == OrderStatus.FAILED
    assert failed.reason is not None and "(Shioaji answered TokenError, status 401). It may have reached the exchange" in failed.reason
    assert [message for message in said(logger) if "lookup" in message] == [
        f"Shioaji lookup of the order tagged {failed.id.hex[:5]}0 failed: Shioaji answered TokenError, status 401"
    ]
    assert private_parts(failed.reason, *said(logger)) == []


async def test_refused_status_reads_and_cancel_are_logged_saying_only_the_error_type_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeShioaji(refusals={"update_status": sdk_refusal(), "cancel_order": sdk_refusal()}, refuses_once_placed=True)
    logger = RecordingLogger()

    failed = await (await broker_of(client, monkeypatch, logger, SystemEnvironment.TEST)).place_order(order(), no_refusal)

    assert failed.status == OrderStatus.FAILED
    assert [message for message in said(logger) if "failed:" in message] == [
        *["Shioaji status refresh failed: Shioaji answered TokenError, status 401"] * 3,
        f"Shioaji cancel of the order tagged {failed.id.hex[:5]}0 failed: Shioaji answered TokenError, status 401",
        *["Shioaji status refresh failed: Shioaji answered TokenError, status 401"] * 3,
    ]
    assert private_parts(failed.reason, *said(logger)) == []


async def test_a_refused_exchange_order_gives_the_brokers_status_code_instead_of_its_message(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.Failed, msg=SERVER_WORDS, status_code="88")]})
    logger = RecordingLogger()

    refused = await (await broker_of(client, monkeypatch, logger, SystemEnvironment.TEST)).place_order(order(), no_refusal)

    assert (refused.status, refused.reason) == (
        OrderStatus.REJECTED,
        "BROKER_REFUSED: Common 1 lots IOC Failed, dealt 0 shares (status 88)",
    )
    assert private_parts(refused.reason, *said(logger)) == []


ORDERING_OFF = (RejectReason.ORDERING_OFF, "this site has ordering on shioaji off: features.sinopac_ordering")


def refusing_from(send: int):
    """The send-time question of a site whose ordering is turned off right before the exchange order numbered `send`."""
    asked = 0

    async def refusal_now() -> tuple[RejectReason, str] | None:
        nonlocal asked
        asked += 1
        return ORDERING_OFF if asked >= send else None

    return refusal_now


async def test_ordering_turned_off_before_the_first_part_sends_nothing_and_the_order_is_rejected_with_it() -> None:
    client = FakeShioaji()

    placed = await provider(client).place_order(order(quantity=1500), refusing_from(1))

    assert client.placed == []
    assert (placed.status, placed.filled_quantity) == (OrderStatus.REJECTED, 0)
    assert placed.reason == f"{RejectReason.ORDERING_OFF.name}: {ORDERING_OFF[1]}"


async def test_ordering_turned_off_between_the_parts_stops_the_odd_lot_and_the_order_says_why() -> None:
    client = FakeShioaji()

    placed = await provider(client).place_order(order(quantity=1500), refusing_from(2))

    assert [(trade.order.order_lot, trade.order.quantity) for trade in client.placed] == [(StockOrderLot.Common, 1)]
    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 1000)
    assert placed.reason is not None and f"the rest was not sent: {ORDERING_OFF[1]}" in placed.reason
