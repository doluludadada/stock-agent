import asyncio
import threading
import time as time_module
import traceback
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pytest
import shioaji
from pydantic import ValidationError
from shioaji.constant import (
    Action,
    OrderState,
    OrderType as BrokerTimeInForce,
    Status,
    StockOrderCond,
    StockOrderLot,
    StockPriceType,
    Unit,
)
from shioaji.error import TimeoutError as ShioajiTimeoutError, TokenError
from shioaji.order import Order as BrokerOrder
from shioaji.position import AccountBalance
from support.fake_shioaji import FakeContracts, FakeShioaji, FakeStocks, OddLotMatches, Report, position, sale, stock
from support.fakes import FakeMarketClock, FakeOrderingSwitch, FakeTradingJournal, FakeUserStore, RecordingLogger, no_refusal
from support.harness import harness_config
from support.settings import shipped_config, sinopac_setup
from trading_stack import SilentLogger, run_stats

from a_domain.model.system.user import User
from a_domain.model.trading.order import Order
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import OrderStatus, OrderType, RejectReason, Role, ShioajiServer, TimeInForce, TradeAction, Workflow
from a_domain.types.errors import BrokerNotAnswering
from a_domain.types.ids import UserId, new_decision_id, new_run_id
from b_application.config.app_config import AppConfig
from b_application.config.trading_config import ShioajiConfig, ShioajiLogin
from b_application.use_cases.trade.order_execution import OrderExecution
from c_infrastructure.market.shioaji_quote_provider import ShioajiConnection, ShioajiQuoteProvider
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock
from c_infrastructure.trading.shioaji import execution_provider
from c_infrastructure.trading.shioaji.execution_provider import ORDER_STATUS, ShioajiExecutionProvider
from d_presentation.dependencies import ProcessState, connect_shioaji

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)

pytestmark = pytest.mark.asyncio

CONFIG = shipped_config()
COSTS = CONFIG.market.cost_rule()
MONDAY = date(2026, 10, 19)


def taipei(moment: time) -> datetime:
    return datetime.combine(MONDAY, moment, TAIWAN_TIMEZONE)


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeMarketClock:
    """Monday 10:00 in Taipei, which every wait of the adapter moves instead of taking the time."""
    market_clock = FakeMarketClock(taipei(time(10, 0)))

    async def wait(seconds: float) -> None:
        market_clock.current_time += timedelta(seconds=seconds)
        await asyncio.sleep(0)

    monkeypatch.setattr(execution_provider, "sleep", wait)
    return market_clock


def provider(
    client: FakeShioaji, clock: FakeMarketClock | None = None, logger: RecordingLogger | None = None, config: AppConfig = CONFIG
) -> ShioajiExecutionProvider:
    if client.stock_account is None:
        client.stock_account = client.account_at_login

    login, connection = login_of(client.simulation), ShioajiConnection(client=client, up=True)
    return ShioajiExecutionProvider(
        connection=connection,
        login=login,
        config=config,
        market_clock=clock or FakeMarketClock(taipei(time(10, 0))),
        logger=logger or SilentLogger(),
    )


def login_of(simulation: bool) -> ShioajiLogin:
    server = ShioajiServer.SIMULATION if simulation else ShioajiServer.PRODUCTION
    login = credentials().model_copy(update={"server": server}).login()
    assert login is not None
    return login


async def connected(client: FakeShioaji, simulation: bool) -> ShioajiExecutionProvider:
    """
    The broker on a client the quote provider logged in, to simulation as test does or production as prod does, once
    its connect() checked the login: the startup's order.
    """
    login, connection = login_of(simulation), ShioajiConnection(client=client)
    quotes = quotes_of(connection, login)
    broker = ShioajiExecutionProvider(
        connection=connection, login=login, config=CONFIG, market_clock=TaiwanMarketClock(CONFIG.market_hours), logger=SilentLogger()
    )
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

    placed = await provider(client).place_order(placing, no_refusal, asyncio.Event())

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

    placed = await provider(client).place_order(order(TradeAction.SELL, quantity=500, price=99.0), no_refusal, asyncio.Event())

    assert sent(client) == [(StockOrderLot.IntradayOdd, 500, BrokerTimeInForce.ROD, 99.0)]
    assert client.placed[0].order.action == Action.Sell
    cost = COSTS.apply(TradeAction.SELL, "2330", 99.0, 500, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.tax) == (OrderStatus.FILLED, 500, cost.tax)
    assert placed.realized_pnl == pytest.approx(cost.net - 500 * 90.0)


async def test_a_mixed_quantity_is_split_into_a_board_lot_ioc_order_and_an_odd_lot_rod_order() -> None:
    client = FakeShioaji()
    placing = order(quantity=2500, price=100.0)

    placed = await provider(client).place_order(placing, no_refusal, asyncio.Event())

    assert sent(client) == [
        (StockOrderLot.Common, 2, BrokerTimeInForce.IOC, 100.0),
        (StockOrderLot.IntradayOdd, 500, BrokerTimeInForce.ROD, 100.0),
    ]
    assert [trade.order.custom_field for trade in client.placed] == [f"{placing.id.hex[:5]}0", f"{placing.id.hex[:5]}1"]
    lots, odd = COSTS.apply(TradeAction.BUY, "2330", 100.0, 2000, now=NOW), COSTS.apply(TradeAction.BUY, "2330", 100.0, 500, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.fee) == (OrderStatus.FILLED, 2500, lots.fee + odd.fee)


async def test_fok_is_sent_as_fok() -> None:
    client = FakeShioaji()

    placed = await provider(client).place_order(order(time_in_force=TimeInForce.FOK), no_refusal, asyncio.Event())

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

    placed = await provider(client).place_order(placing, no_refusal, asyncio.Event())

    assert (placed.status, client.placed) == (OrderStatus.REJECTED, [])
    assert placed.reason is not None and placed.reason.startswith(reason)


async def test_a_buy_is_refused_when_cash_minus_settlement_payments_due_cannot_pay_it() -> None:
    client = FakeShioaji(simulation=False, settlement_amounts=(0.0, 50_000.0, -950_000.0))

    placed = await provider(client).place_order(order(quantity=1000, price=100.0), no_refusal, asyncio.Event())

    assert (placed.status, client.placed) == (OrderStatus.REJECTED, [])
    assert placed.reason == "INSUFFICIENT_CASH: needs 100,142 including fee, cash is 50,000"


async def test_selling_more_than_the_broker_holds_is_refused() -> None:
    client = FakeShioaji(holdings=[position("2330", 1000, 90.0)])

    placed = await provider(client).place_order(order(TradeAction.SELL, quantity=2000), no_refusal, asyncio.Event())

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

    placed = await provider(client).place_order(order(), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity, placed.reason, client.cancelled) == (status, filled, reason, [])


@pytest.mark.parametrize("working", [Status.PendingSubmit, Status.PreSubmitted, Status.Submitted, Status.PartFilled])
async def test_an_order_still_working_after_the_polls_is_cancelled(working: Status) -> None:
    deals = ((100.0, 1),) if working == Status.PartFilled else ()
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(working, deals)]})

    placed = await provider(client).place_order(order(quantity=2000), no_refusal, asyncio.Event())

    assert client.cancelled == client.placed
    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 1000 if deals else 0)
    assert placed.reason is not None and placed.reason.startswith(f"IOC unfilled: filled {1000 if deals else 0} of 2000")


async def test_a_partial_fill_is_recorded_before_the_ioc_remainder_is_cancelled() -> None:
    client = FakeShioaji(
        scripts={StockOrderLot.Common: [Report(Status.PartFilled, ((100.0, 1),)), Report(Status.Cancelled, ((100.0, 1),))]}
    )

    placed = await provider(client).place_order(order(quantity=3000), no_refusal, asyncio.Event())

    cost = COSTS.apply(TradeAction.BUY, "2330", 100.0, 1000, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.fee, client.cancelled) == (OrderStatus.CANCELLED, 1000, cost.fee, [])


async def test_an_order_still_working_after_the_cancel_is_left_unconfirmed_with_what_it_filled() -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.PartFilled, ((100.0, 1),))]}, honours_cancel=False)

    placed = await provider(client).place_order(order(quantity=2000), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity, client.cancelled) == (OrderStatus.UNCONFIRMED, 1000, client.placed)
    assert placed.reason == (
        "unconfirmed at Shioaji, whose record of today settles it: Common 2 lots IOC PartFilled, dealt 1000 shares"
    )


async def test_filled_without_deals_for_the_whole_quantity_fails_instead_of_guessing() -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.Filled, ((100.0, 1),))]})

    placed = await provider(client).place_order(order(quantity=2000), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FAILED, 1000)


async def test_deals_at_several_prices_fill_at_their_volume_weighted_price() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Filled, ((10.05, 300), (10.05, 300), (10.0, 399)))]})

    placed = await provider(client).place_order(order(quantity=999, price=10.05), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FILLED, 999)
    assert placed.average_filled_price == pytest.approx((10.05 * 600 + 10.0 * 399) / 999)


async def test_deals_at_the_limit_price_fill_even_where_their_float_average_rounds_above_it() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Filled, ((10.8, 1), (10.8, 1), (10.8, 1)))]})

    placed = await provider(client).place_order(order(quantity=3, price=10.8), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FILLED, 3)
    assert placed.average_filled_price == pytest.approx(10.8)


async def test_when_the_odd_lot_part_is_refused_the_board_lot_fill_stands_and_the_order_is_cancelled() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Failed, msg="price out of range", status_code="88")]})

    placed = await provider(client).place_order(order(quantity=1500), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 1000)
    assert placed.reason is not None and "IntradayOdd 500 shares ROD Failed, dealt 0 shares (status 88)" in placed.reason


async def test_an_odd_lot_rod_part_still_working_after_the_polls_is_cancelled_and_the_order_says_so() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Submitted)]})

    placed = await provider(client).place_order(order(quantity=1500), no_refusal, asyncio.Event())

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

    placed = await provider(client).place_order(order(quantity=1500), no_refusal, asyncio.Event())

    lots, odd = COSTS.apply(TradeAction.BUY, "2330", 100.0, 1000, now=NOW), COSTS.apply(TradeAction.BUY, "2330", 100.0, 200, now=NOW)
    assert (placed.status, placed.filled_quantity, placed.fee) == (OrderStatus.CANCELLED, 1200, lots.fee + odd.fee)
    assert placed.reason is not None and placed.reason.endswith("IntradayOdd 500 shares ROD Cancelled, dealt 200 shares")


async def test_an_odd_lot_rod_part_the_broker_keeps_working_after_the_cancel_leaves_the_order_unconfirmed() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Submitted)]}, honours_cancel=False)

    placed = await provider(client).place_order(order(quantity=500), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity, client.cancelled) == (OrderStatus.UNCONFIRMED, 0, client.placed)
    assert placed.reason == (
        "unconfirmed at Shioaji, whose record of today settles it: IntradayOdd 500 shares ROD Submitted, dealt 0 shares"
    )


def on_the_session(clock: FakeMarketClock, scripts: dict[StockOrderLot, list[Report]] | None = None) -> FakeShioaji:
    """A broker on the test's clock whose odd-lot orders deal at the shipped odd-lot session's matches only."""
    hours = CONFIG.market_hours
    matches = OddLotMatches(first=taipei(hours.odd_lot_start), interval=timedelta(seconds=hours.odd_lot_match_seconds))
    return FakeShioaji(scripts=scripts or {}, clock=clock.now, odd_lot_matches=matches)


async def test_an_odd_lot_part_ordered_before_the_odd_lot_session_goes_at_once_and_deals_at_its_first_match(
    clock: FakeMarketClock,
) -> None:
    """Measured on 2026-11-18: odd-lot IOC parts sent at 09:05 on the simulation server were cancelled before 09:10 unfilled."""
    clock.current_time = taipei(time(9, 5, 15))
    client, asked_at = on_the_session(clock), []

    async def refusal_now() -> tuple[RejectReason, str] | None:
        asked_at.append(clock.now())
        return None

    placed = await provider(client, clock).place_order(order(quantity=1500), refusal_now, asyncio.Event())

    assert client.placed_at == asked_at == [taipei(time(9, 5, 15))] * 2
    assert [trade.order.order_type for trade in client.placed] == [BrokerTimeInForce.IOC, BrokerTimeInForce.ROD]
    assert (placed.status, placed.filled_quantity, client.cancelled) == (OrderStatus.FILLED, 1500, [])


async def test_an_odd_lot_part_ordered_before_the_odd_lot_session_works_through_its_first_match_and_the_next_ones(
    clock: FakeMarketClock,
) -> None:
    clock.current_time = taipei(time(9, 5, 15))
    client = on_the_session(clock, {StockOrderLot.IntradayOdd: [Report(Status.Submitted)]})

    placed = await provider(client, clock).place_order(order(quantity=500), no_refusal, asyncio.Event())

    [placed_at], [cancelled_at] = client.placed_at, client.cancelled_at
    hours, matches = CONFIG.market_hours, CONFIG.shioaji.odd_lot_matches
    assert cancelled_at == taipei(hours.odd_lot_start) + timedelta(seconds=(matches + 0.5) * hours.odd_lot_match_seconds)
    assert client.odd_lot_matches is not None and client.odd_lot_matches.between(placed_at, cancelled_at) == matches + 1
    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 0)


ADMIN = User(user_id=UserId("u-admin"), username="admin", email="admin@example.com", role=Role.ADMINISTRATOR, created_at=NOW)


def sinopac_run(client: FakeShioaji, clock: FakeMarketClock) -> tuple[OrderExecution, FakeTradingJournal]:
    """OrderExecution of an administrator's manual BUY on SinoPac's simulation server, ordering shown to everyone."""
    config, users, journal = harness_config(), FakeUserStore(), FakeTradingJournal()
    users.add(ADMIN, None)
    switch = FakeOrderingSwitch(config.features, ShioajiServer.SIMULATION)
    return OrderExecution(provider(client, clock), journal, users, switch, ADMIN.user_id, clock, config, SilentLogger()), journal


def holding_the_wait_from(clock: FakeMarketClock, moment: datetime, monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    """Every wait of the adapter moves the clock, until one starts at `moment` or later: that one holds until cancelled."""
    held = asyncio.Event()

    async def wait(seconds: float) -> None:
        if clock.now() >= moment:
            held.set()
            await asyncio.Event().wait()

        clock.current_time += timedelta(seconds=seconds)
        await asyncio.sleep(0)

    monkeypatch.setattr(execution_provider, "sleep", wait)
    return held


async def cancelled_while(run: asyncio.Task[Order], held: asyncio.Event) -> None:
    await held.wait()
    run.cancel()

    with pytest.raises(asyncio.CancelledError):
        await run


class HeldOrderingSwitch(FakeOrderingSwitch):
    """The settings files read in a thread, as the real switch does: the test holds the read until it lets it go."""

    def __init__(self, switch: FakeOrderingSwitch) -> None:
        super().__init__(switch.features, switch.server)
        self.reading, self.release = asyncio.Event(), asyncio.Event()

    async def read(self):  # noqa: ANN201
        self.reading.set()
        await self.release.wait()
        return await super().read()


async def test_a_run_cancelled_while_the_gate_reads_the_ordering_switch_before_a_send_sends_nothing(clock: FakeMarketClock) -> None:
    client = FakeShioaji(clock=clock.now)
    config, users, journal = harness_config(), FakeUserStore(), FakeTradingJournal()
    users.add(ADMIN, None)
    switch = HeldOrderingSwitch(FakeOrderingSwitch(config.features, ShioajiServer.SIMULATION))
    execution = OrderExecution(provider(client, clock), journal, users, switch, ADMIN.user_id, clock, config, SilentLogger())
    placing = order(quantity=1000)

    run = asyncio.create_task(execution.execute(placing, run_stats(Workflow.MANUAL_BUY)))
    await switch.reading.wait()
    run.cancel()
    await asyncio.sleep(0)
    switch.release.set()

    with pytest.raises(asyncio.CancelledError):
        await run

    assert client.placed == []
    saved = journal.orders[placing.id]
    assert (saved.status, saved.filled_quantity) == (OrderStatus.REJECTED, 0)
    assert saved.reason is not None and "the run was cancelled before it was sent" in saved.reason


async def test_a_run_cancelled_while_its_odd_lot_part_waits_for_the_first_match_cancels_it_at_once_and_sends_nothing_more(
    clock: FakeMarketClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found in review: a run cancelled at 09:00:30 still sent the odd-lot part at 09:10, after the cancel."""
    clock.current_time = taipei(time(9, 0, 30))
    client = on_the_session(clock)
    held = holding_the_wait_from(clock, clock.now(), monkeypatch)
    execution, journal = sinopac_run(client, clock)
    placing = order(quantity=1500)

    await cancelled_while(asyncio.create_task(execution.execute(placing, run_stats(Workflow.MANUAL_BUY))), held)

    [_, odd_lot] = client.placed
    assert [trade.order.order_lot for trade in client.placed] == [StockOrderLot.Common, StockOrderLot.IntradayOdd]
    assert (client.cancelled, client.cancelled_at) == ([odd_lot], [taipei(time(9, 0, 30))])
    saved = journal.orders[placing.id]
    assert (saved.status, saved.filled_quantity) == (OrderStatus.CANCELLED, 1000)
    assert saved.reason is not None and saved.reason.endswith("IntradayOdd 500 shares ROD Cancelled, dealt 0 shares")


async def test_a_run_cancelled_after_its_odd_lot_part_dealt_at_a_match_records_the_deal_and_cancels_the_rest(
    clock: FakeMarketClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock.current_time = taipei(time(9, 5))
    client = on_the_session(clock, {StockOrderLot.IntradayOdd: [Report(Status.PartFilled, ((100.0, 200),)), Report(Status.Filled)]})
    held = holding_the_wait_from(clock, taipei(CONFIG.market_hours.odd_lot_start), monkeypatch)
    execution, journal = sinopac_run(client, clock)
    placing = order(quantity=1500)

    await cancelled_while(asyncio.create_task(execution.execute(placing, run_stats(Workflow.MANUAL_BUY))), held)

    [_, odd_lot] = client.placed
    assert client.cancelled == [odd_lot]
    saved = journal.orders[placing.id]
    lots, odd = COSTS.apply(TradeAction.BUY, "2330", 100.0, 1000, now=NOW), COSTS.apply(TradeAction.BUY, "2330", 100.0, 200, now=NOW)
    assert (saved.status, saved.filled_quantity, saved.fee) == (OrderStatus.CANCELLED, 1200, lots.fee + odd.fee)
    assert saved.reason is not None and saved.reason.endswith("IntradayOdd 500 shares ROD Cancelled, dealt 200 shares")


async def test_a_run_cancelled_while_its_board_lot_part_is_sent_finishes_that_send_and_never_sends_the_odd_lot_part(
    clock: FakeMarketClock,
) -> None:
    client = FakeShioaji(clock=clock.now, place_gate=threading.Event())
    execution, journal = sinopac_run(client, clock)
    placing = order(quantity=1500)
    run = asyncio.create_task(execution.execute(placing, run_stats(Workflow.MANUAL_BUY)))

    while not client.placed:
        await asyncio.sleep(0.001)

    run.cancel()
    await asyncio.sleep(0.01)
    assert client.place_gate is not None
    client.place_gate.set()

    with pytest.raises(asyncio.CancelledError):
        await run

    assert [trade.order.order_lot for trade in client.placed] == [StockOrderLot.Common]
    saved = journal.orders[placing.id]
    assert (saved.status, saved.filled_quantity) == (OrderStatus.CANCELLED, 1000)
    assert saved.reason is not None and saved.reason.endswith(
        "Common 1 lots IOC Filled, dealt 1000 shares; the rest was not sent: the run was cancelled before it was sent"
    )


async def test_a_cancel_the_broker_does_not_settle_within_its_timeout_leaves_the_order_unconfirmed() -> None:
    client = FakeShioaji(scripts={StockOrderLot.IntradayOdd: [Report(Status.Submitted)]}, status_gate=threading.Event())
    config = CONFIG.model_copy(update={"shioaji": CONFIG.shioaji.model_copy(update={"cancel_timeout_seconds": 0.05})})
    broker = provider(client, config=config)

    try:
        placed = await asyncio.wait_for(broker.place_order(order(quantity=500), no_refusal, asyncio.Event()), timeout=2)
    finally:
        assert client.status_gate is not None
        client.status_gate.set()

    assert (placed.status, client.cancelled) == (OrderStatus.UNCONFIRMED, client.placed)
    assert placed.reason is not None and placed.reason.startswith("unconfirmed at Shioaji, whose record of today settles it")


@pytest.mark.parametrize(
    "setting",
    [{"odd_lot_matches": 11}, {"cancel_timeout_seconds": 31}, {"cancel_timeout_seconds": 0}],
    ids=["matches", "cancel-timeout-long", "cancel-timeout-zero"],
)
def test_an_odd_lot_window_or_a_cancel_wait_past_its_bound_is_refused_naming_the_setting(setting: dict[str, float]) -> None:
    with pytest.raises(ValidationError, match=next(iter(setting))):
        ShioajiConfig(_env_file=None, poll_interval_seconds=0, max_polls=3, **setting)


async def test_an_odd_lot_part_that_does_not_deal_stays_working_through_its_matches_before_the_rest_is_cancelled(
    clock: FakeMarketClock,
) -> None:
    client = on_the_session(clock, {StockOrderLot.IntradayOdd: [Report(Status.Submitted)]})

    placed = await provider(client, clock).place_order(order(quantity=500), no_refusal, asyncio.Event())

    [placed_at], [cancelled_at] = client.placed_at, client.cancelled_at
    assert placed_at == taipei(time(10, 0))
    assert client.odd_lot_matches is not None
    assert client.odd_lot_matches.between(placed_at, cancelled_at) == CONFIG.shioaji.odd_lot_matches
    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 0)
    assert placed.reason is not None and placed.reason.endswith("IntradayOdd 500 shares ROD Cancelled, dealt 0 shares")


async def test_an_odd_lot_part_that_deals_at_its_last_match_fills_the_order_without_a_cancel(clock: FakeMarketClock) -> None:
    waiting = [Report(Status.Submitted)] * (CONFIG.shioaji.odd_lot_matches - 1)
    client = on_the_session(clock, {StockOrderLot.IntradayOdd: [*waiting, Report(Status.Filled, ((100.0, 500),))]})

    placed = await provider(client, clock).place_order(order(quantity=1500), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity, client.cancelled) == (OrderStatus.FILLED, 1500, [])


async def test_an_odd_lot_part_partly_dealt_at_its_last_match_records_the_deal_and_cancels_the_rest(clock: FakeMarketClock) -> None:
    waiting = [Report(Status.Submitted)] * (CONFIG.shioaji.odd_lot_matches - 1)
    client = on_the_session(clock, {StockOrderLot.IntradayOdd: [*waiting, Report(Status.PartFilled, ((100.0, 200),))]})

    placed = await provider(client, clock).place_order(order(quantity=1500), no_refusal, asyncio.Event())

    [_, odd_lot] = client.placed
    assert client.cancelled == [odd_lot]
    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 1200)
    assert placed.reason is not None and placed.reason.endswith("IntradayOdd 500 shares ROD Cancelled, dealt 200 shares")


async def test_a_board_lot_part_still_working_is_cancelled_after_its_polls(clock: FakeMarketClock) -> None:
    client = on_the_session(clock, {StockOrderLot.Common: [Report(Status.Submitted)]})

    placed = await provider(client, clock).place_order(order(quantity=1000), no_refusal, asyncio.Event())

    [placed_at], [cancelled_at] = client.placed_at, client.cancelled_at
    polling = CONFIG.shioaji
    assert cancelled_at - placed_at == timedelta(seconds=(polling.max_polls - 1) * polling.poll_interval_seconds)
    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 0)


PERSON_ID, ACCOUNT_ID, BROKER_ID = "A123456789", "9876543", "9A95"
ORDER_IDS = ("97b63e2f", "267677", "IM394", "9c6ae2eb", "669915", "web137")
"""The broker's own ids of the order and its deal. The tag (custom_field) is the app's: its journal row's id prefix."""
ORDER_EVENT = {
    "operation": {"op_type": "New", "op_code": "00", "op_msg": f"accepted for {PERSON_ID}"},
    "order": {
        "id": "97b63e2f",
        "seqno": "267677",
        "ordno": "IM394",
        "account": {"account_type": "S", "person_id": PERSON_ID, "broker_id": BROKER_ID, "account_id": ACCOUNT_ID, "signed": True},
        "action": "Buy",
        "price": 218.0,
        "quantity": 229,
        "order_type": "ROD",
        "price_type": "LMT",
        "order_cond": "Cash",
        "order_lot": "IntradayOdd",
        "custom_field": "f00ba0",
    },
    "status": {"id": "97b63e2f", "exchange_ts": 1763427920.0, "order_quantity": 229, "web_id": "web137"},
    "contract": {"security_type": "STK", "exchange": "TSE", "code": "5209", "symbol": "TSE5209", "name": "5209", "currency": "TWD"},
}
DEAL_EVENT = {
    "trade_id": "9c6ae2eb",
    "seqno": "267677",
    "ordno": "IM394",
    "exchange_seq": "669915",
    "broker_id": BROKER_ID,
    "account_id": ACCOUNT_ID,
    "action": "Buy",
    "code": "5209",
    "order_cond": "Cash",
    "order_lot": "IntradayOdd",
    "price": 217.5,
    "quantity": 100,
    "web_id": "web137",
    "custom_field": "f00ba0",
    "ts": 1763427925.0,
}


def logged_in(logger: RecordingLogger) -> tuple[FakeShioaji, ShioajiQuoteProvider, ShioajiConnection]:
    """A client the quote provider logs in on, its order events logged to `logger`, once connect() is awaited."""
    client = FakeShioaji()
    connection = ShioajiConnection(client=client)
    quotes = ShioajiQuoteProvider(
        connection=connection,
        new_client=FakeShioaji,
        login=login_of(simulation=True),
        market_clock=TaiwanMarketClock(CONFIG.market_hours),
        market_data=CONFIG.market_data,
        board_lot_shares=1000,
        logger=logger,
    )
    return client, quotes, connection


async def test_the_login_logs_each_order_event_with_its_tag_and_without_the_account_or_the_brokers_order_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logger = RecordingLogger()
    client, quotes, _ = logged_in(logger)
    await quotes.connect()
    assert client.order_callback is not None

    client.order_callback(OrderState.StockOrder, ORDER_EVENT)
    client.order_callback(OrderState.StockDeal, DEAL_EVENT)

    assert [record for record in logger.records if record[1].startswith("Shioaji order event") or "deal" in record[1]] == [
        ("info", "Shioaji order event New 00 tagged f00ba0: Buy 5209 IntradayOdd 229 at 218.0"),
        ("info", "Shioaji deal tagged f00ba0: Buy 5209 IntradayOdd 100 at 217.5"),
    ]
    printed = capsys.readouterr()
    shown = "\n".join([printed.out, printed.err, *said(logger)])
    assert [value for value in (PERSON_ID, ACCOUNT_ID, BROKER_ID, *ORDER_IDS) if value in shown] == []


async def test_an_order_sent_on_the_login_logs_its_events_from_the_sdks_thread_without_the_account(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logger = RecordingLogger()
    client, quotes, connection = logged_in(logger)
    await quotes.connect()
    client.scripts = {StockOrderLot.IntradayOdd: [Report(Status.PartFilled, ((100.0, 200),))]}
    broker = ShioajiExecutionProvider(
        connection=connection, login=login_of(True), config=CONFIG, market_clock=FakeMarketClock(NOW), logger=SilentLogger()
    )

    placed = await broker.place_order(order(quantity=1500), no_refusal, asyncio.Event())

    events = [message for level, message in logger.records if level == "info"]
    tag = placed.id.hex[:5]
    assert events == [
        f"Shioaji order event New 00 tagged {tag}0: Buy 2330 Common 1 at 100.0",
        f"Shioaji deal tagged {tag}0: Buy 2330 Common 1 at 100.0",
        f"Shioaji order event New 00 tagged {tag}1: Buy 2330 IntradayOdd 500 at 100.0",
        f"Shioaji deal tagged {tag}1: Buy 2330 IntradayOdd 200 at 100.0",
    ]
    account = client.account_at_login
    assert account is not None
    printed = capsys.readouterr()
    shown = "\n".join([printed.out, printed.err, *said(logger)])
    assert [value for value in (account.person_id, account.account_id, account.broker_id) if value in shown] == []


class UnreadableEvent(dict):
    """An event whose every read raises, quoting the person id as an SDK's error might."""

    def get(self, key, default=None):
        raise KeyError(PERSON_ID)


@pytest.mark.parametrize(("event", "error"), [("not a mapping", "AttributeError"), (UnreadableEvent(), "KeyError")])
async def test_an_order_event_the_callback_cannot_read_is_one_warning_without_its_contents_and_never_reaches_the_sdk(
    event: object, error: str
) -> None:
    logger = RecordingLogger()
    client, quotes, _ = logged_in(logger)
    await quotes.connect()
    assert client.order_callback is not None

    client.order_callback(OrderState.StockOrder, event)

    assert [record for record in logger.records if "order event" in record[1]] == [
        ("warning", f"Shioaji order event not logged: {error}")
    ]
    assert PERSON_ID not in "\n".join(said(logger))


async def test_when_every_part_is_refused_the_order_is_rejected_by_the_broker() -> None:
    client = FakeShioaji(scripts={lot: [Report(Status.Failed, msg="closing auction")] for lot in StockOrderLot})

    placed = await provider(client).place_order(order(quantity=1500), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity, len(client.placed)) == (OrderStatus.REJECTED, 0, 2)
    assert placed.reason is not None and placed.reason.startswith("BROKER_REFUSED: Common 1 lots IOC Failed")


async def test_a_timed_out_place_order_is_found_by_its_tag_and_settled() -> None:
    client = FakeShioaji(place_error=ShioajiTimeoutError("place_order", {}), place_error_after_accepting=True)

    placed = await provider(client).place_order(order(), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FILLED, 1000)


async def test_a_timed_out_place_order_on_a_busy_day_is_still_found_by_its_tag() -> None:
    client = FakeShioaji(
        place_error=ShioajiTimeoutError("place_order", {}),
        place_error_after_accepting=True,
        account_refresh_milliseconds=BUSY_DAY_MILLISECONDS,
    )

    placed = await provider(client).place_order(order(), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FILLED, 1000)
    assert set(client.account_refreshes) == {30_000}


LATE_DEALS = ((114.0, 150), (114.5, 280))
"""An odd-lot BUY of 430 shares of 3029 at 114.5, dealt in two matches, as the one of 2026-11-19 dealt all of it."""


def lost_answer(listed_after: int, scripts: dict[StockOrderLot, list[Report]] | None = None) -> FakeShioaji:
    """
    A broker whose answer to place_order comes after the SDK's wait, as pysolace's SolClient.request drops it: the
    order went out, and the broker lists it only after `listed_after` more account-wide refreshes.
    """
    return FakeShioaji(
        Contracts=FakeContracts(FakeStocks({"3029": stock("3029", 114.5), "2330": stock("2330")})),
        scripts=scripts or {},
        place_error=ShioajiTimeoutError("place_order", {}),
        place_error_after_accepting=True,
        unlisted_refreshes=listed_after,
    )


async def test_an_order_the_broker_lists_a_moment_after_its_answer_was_lost_is_read_and_recorded_as_if_confirmed() -> None:
    client = lost_answer(
        1, {StockOrderLot.IntradayOdd: [Report(Status.PartFilled, LATE_DEALS[:1]), Report(Status.Filled, LATE_DEALS)]}
    )

    placed = await provider(client).place_order(order(quantity=430, price=114.5, stock_id="3029"), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FILLED, 430)
    assert placed.average_filled_price == pytest.approx((114.0 * 150 + 114.5 * 280) / 430)
    assert "@ 114.3" in placed.summary, "the summary shows the price it filled at, not the limit"


async def test_a_part_the_broker_lists_late_and_still_working_after_its_reads_is_cancelled_so_nothing_is_left_working() -> None:
    client = lost_answer(1, {StockOrderLot.IntradayOdd: [Report(Status.Submitted)] * 20})

    placed = await provider(client).place_order(order(quantity=430, price=114.5, stock_id="3029"), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 0)
    assert [trade.status.status for trade in client.placed] == [Status.Cancelled]


async def test_settling_an_order_listed_after_the_first_look_cancels_what_still_works_and_records_what_dealt() -> None:
    client = lost_answer(CONFIG.shioaji.max_polls, {StockOrderLot.IntradayOdd: [Report(Status.PartFilled, LATE_DEALS[:1])]})
    broker = provider(client)
    placed = await broker.place_order(order(quantity=430, price=114.5, stock_id="3029"), no_refusal, asyncio.Event())
    assert (placed.status, placed.filled_quantity) == (OrderStatus.UNCONFIRMED, 0)

    await broker.settle(placed)

    assert (placed.status, placed.filled_quantity, placed.average_filled_price) == (OrderStatus.CANCELLED, 150, 114.0)
    assert placed.reason == "IOC unfilled: filled 150 of 430; IntradayOdd 430 shares ROD Cancelled, dealt 150 shares"
    assert [trade.status.status for trade in client.placed] == [Status.Cancelled]


async def test_settling_records_only_the_deals_the_order_does_not_hold_yet_and_settling_again_changes_nothing() -> None:
    client = lost_answer(CONFIG.shioaji.max_polls)
    client.place_error_lot = StockOrderLot.IntradayOdd
    broker = provider(client)
    placed = await broker.place_order(order(quantity=1430), no_refusal, asyncio.Event())
    assert (placed.status, placed.filled_quantity) == (OrderStatus.UNCONFIRMED, 1000), "the board lot filled, the odd lot unread"

    await broker.settle(placed)
    settled = replace(placed)
    await broker.settle(placed)

    lots, odd = COSTS.apply(TradeAction.BUY, "2330", 100.0, 1000, now=NOW), COSTS.apply(TradeAction.BUY, "2330", 100.0, 430, now=NOW)
    assert (settled.status, settled.filled_quantity, settled.fee) == (OrderStatus.FILLED, 1430, lots.fee + odd.fee)
    assert placed == settled


@pytest.mark.parametrize(
    ("settled_at", "status"),
    [(time(13, 31), OrderStatus.UNCONFIRMED), (time(14, 59), OrderStatus.UNCONFIRMED), (time(15, 0), OrderStatus.FAILED)],
)
async def test_settling_an_order_the_broker_never_lists_waits_until_its_sessions_deals_are_final_and_then_fails_it(
    clock: FakeMarketClock, settled_at: time, status: OrderStatus
) -> None:
    client = lost_answer(10**6)
    broker = provider(client, clock)
    placed = await broker.place_order(order(quantity=430, price=114.5, stock_id="3029"), no_refusal, asyncio.Event())

    clock.current_time = taipei(settled_at)
    await broker.settle(placed)

    assert (placed.status, placed.filled_quantity) == (status, 0)
    assert status == OrderStatus.UNCONFIRMED or (placed.reason or "").startswith("Shioaji never listed it by its session's end")


@pytest.mark.parametrize(("settled_at", "status"), [(time(13, 30, 2), OrderStatus.UNCONFIRMED), (time(15, 0), OrderStatus.CANCELLED)])
async def test_a_part_still_working_after_the_close_stays_unconfirmed_until_the_days_deals_are_final(
    clock: FakeMarketClock, settled_at: time, status: OrderStatus
) -> None:
    client = lost_answer(CONFIG.shioaji.max_polls, {StockOrderLot.IntradayOdd: [Report(Status.Submitted)] * 50})
    client.honours_cancel = False
    broker = provider(client, clock)
    placed = await broker.place_order(order(quantity=430, price=114.5, stock_id="3029"), no_refusal, asyncio.Event())

    clock.current_time = taipei(settled_at)
    await broker.settle(placed)

    assert (placed.status, placed.filled_quantity) == (status, 0), "a closing-auction deal may still be reported before then"


async def test_settling_a_part_that_dealt_at_its_limit_records_it_at_exactly_the_limit() -> None:
    client = lost_answer(CONFIG.shioaji.max_polls, {StockOrderLot.IntradayOdd: [Report(Status.Filled, ((12.45, 329),))]})
    broker = provider(client)
    placed = await broker.place_order(order(quantity=329, price=12.45), no_refusal, asyncio.Event())
    assert placed.status == OrderStatus.UNCONFIRMED

    await broker.settle(placed)

    assert 12.45 * 329 / 329 > 12.45, "the volume-weighted price of one deal at the limit lands past it in floats"
    assert (placed.status, placed.filled_quantity, placed.average_filled_price) == (OrderStatus.FILLED, 329, 12.45)


@pytest.mark.parametrize(
    ("held_after", "realized_pnl"),
    [([], None), ([position("2330", 500, 90.0)], COSTS.apply(TradeAction.SELL, "2330", 100.0, 1000, now=NOW).net - 1000 * 90.0)],
    ids=["every share sold", "shares left"],
)
async def test_settling_a_sale_takes_its_cost_from_the_position_left_and_says_when_none_is_left(
    held_after: list, realized_pnl: float | None
) -> None:
    client = lost_answer(CONFIG.shioaji.max_polls)
    client.holdings = [position("2330", 1500, 90.0)]
    broker = provider(client)
    placed = await broker.place_order(order(TradeAction.SELL), no_refusal, asyncio.Event())
    assert placed.status == OrderStatus.UNCONFIRMED
    client.holdings = held_after

    await broker.settle(placed)

    assert (placed.status, placed.filled_quantity) == (OrderStatus.FILLED, 1000)
    assert placed.realized_pnl == (None if realized_pnl is None else pytest.approx(realized_pnl))
    assert placed.reason == (
        None if held_after else "realized PnL not computed: Shioaji lists no 2330 position after the sale to take its cost from"
    )


async def test_settling_the_rest_of_a_sale_of_every_share_keeps_no_realized_pnl_of_the_part_sold_before() -> None:
    """The board-lot part's PnL was computed in the run; the odd-lot part's, settled once nothing is held, cannot be."""
    client = lost_answer(CONFIG.shioaji.max_polls)
    client.place_error_lot = StockOrderLot.IntradayOdd
    client.holdings = [position("2330", 1430, 90.0)]
    broker = provider(client)
    placed = await broker.place_order(order(TradeAction.SELL, quantity=1430), no_refusal, asyncio.Event())
    assert (placed.status, placed.filled_quantity, placed.realized_pnl is not None) == (OrderStatus.UNCONFIRMED, 1000, True)
    client.holdings = []

    await broker.settle(placed)

    assert (placed.status, placed.filled_quantity, placed.realized_pnl) == (OrderStatus.FILLED, 1430, None)
    assert placed.reason == "realized PnL not computed: Shioaji lists no 2330 position after the sale to take its cost from"


async def test_the_look_for_an_order_whose_answer_was_lost_ends_once_the_run_is_cancelled() -> None:
    client = lost_answer(10**6)
    stop = asyncio.Event()
    stop.set()

    placed = await provider(client).place_order(order(), no_refusal, stop)

    assert placed.status == OrderStatus.UNCONFIRMED
    assert len(client.account_refreshes) == 2, "the read before the send, then one lookup"


async def test_the_look_for_an_order_whose_answer_was_lost_ends_within_the_status_timeout_in_all() -> None:
    client = lost_answer(10**6)
    client.account_refresh_seconds = 0.2
    config = CONFIG.model_copy(update={"shioaji": CONFIG.shioaji.model_copy(update={"status_timeout_seconds": 0.5})})
    started = time_module.monotonic()

    placed = await provider(client, config=config).place_order(order(), no_refusal, asyncio.Event())

    assert placed.status == OrderStatus.UNCONFIRMED
    assert time_module.monotonic() - started < 1.5, "ten lookups of 0.2 s each would take 2 s"
    assert len(client.account_refreshes) <= 5


@pytest.mark.parametrize(
    ("stock_id", "action", "lots", "price"),
    [("3029", Action.Buy, 1, 100.0), ("2330", Action.Sell, 1, 100.0), ("2330", Action.Buy, 2, 100.0), ("2330", Action.Buy, 1, 101.0)],
    ids=["another stock", "another action", "another quantity", "another price"],
)
async def test_another_order_listed_under_the_same_tag_is_never_taken_for_a_part_nor_cancelled(
    stock_id: str, action: Action, lots: int, price: float
) -> None:
    client = lost_answer(10**6, {StockOrderLot.Common: [Report(Status.Submitted)] * 50})
    client.place_error = None
    placing = order()
    other = BrokerOrder(
        price=price,
        quantity=lots,
        action=action,
        price_type=StockPriceType.LMT,
        order_type=BrokerTimeInForce.ROD,
        order_lot=StockOrderLot.Common,
        order_cond=StockOrderCond.Cash,
        account=client.stock_account or client.account_at_login,
        custom_field=f"{placing.id.hex[:5]}0",
    )
    client.place_order(client.Contracts.Stocks[stock_id], other)
    client.place_error = ShioajiTimeoutError("place_order", {})
    broker = provider(client)

    placed = await broker.place_order(placing, no_refusal, asyncio.Event())
    await broker.settle(placed)

    assert (placed.status, placed.filled_quantity, client.cancelled) == (OrderStatus.UNCONFIRMED, 0, [])


async def test_an_order_whose_answer_was_lost_and_the_broker_does_not_list_is_left_unconfirmed_naming_its_tag() -> None:
    client = FakeShioaji(place_error=ShioajiTimeoutError("place_order", {}))

    placed = await provider(client).place_order(order(), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity) == (OrderStatus.UNCONFIRMED, 0)
    assert placed.reason == (
        f"unconfirmed at Shioaji, whose record of today settles it: Common 1000 shares tagged {placed.id.hex[:5]}0, "
        "which Shioaji does not list"
    )
    assert len(client.account_refreshes) == 1 + CONFIG.shioaji.max_polls, "the read before the send, then each lookup"


async def test_get_account_reads_cash_less_payments_due_and_the_long_cash_positions_in_shares() -> None:
    client = FakeShioaji(
        simulation=False,
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
    client = FakeShioaji(simulation=False)
    client.balance = client.balance.model_copy(update={"errmsg": "bank link down"})

    with pytest.raises(RuntimeError, match="^Shioaji answered the account balance with an error message$"):
        await provider(client).get_account()


async def test_the_statement_is_the_account_as_the_broker_reports_it_and_sends_nothing() -> None:
    client = FakeShioaji(
        simulation=False,
        settlement_amounts=(-10_000.0, 0.0, 20_000.0),
        holdings=[
            position("2330", 1500, 95.5).model_copy(update={"last_price": 104.0, "pnl": 12_345.0}),
            position("2603", 2000, 50.0, cond=StockOrderCond.MarginTrading),
            position("6505", 37, 80.0).model_copy(update={"last_price": 0.0}),
        ],
        profit_losses=[sale("2317", 1000, 58.0, -2_300.0, "2026-10-09"), sale("1101", 37, 35.0, 10.0, "2025-09-01")],
    )
    broker = provider(client)
    await broker.place_order(order(quantity=1500), no_refusal, asyncio.Event())
    sent = list(client.placed)

    statement = await broker.statement(date(2026, 7, 21), date(2026, 10, 19))

    assert (statement.simulation, statement.balance, statement.sales_from) == (False, 1_000_000, date(2026, 7, 21))
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
    client = FakeShioaji(simulation=False)
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

    fills = (await broker.statement(date(2026, 10, 19), date(2026, 10, 19))).fills

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
    client = FakeShioaji(simulation=False, refusals={read: sdk_refusal()})

    with pytest.raises(RuntimeError, match="^Shioaji answered TokenError, status 401$") as refused:
        await provider(client).statement(date(2026, 7, 21), date(2026, 10, 19))

    assert private_parts(raised(refused.value)) == [] and client.placed == []


BUSY_DAY_MILLISECONDS = 8_000
"""An account-wide refresh slower than the SDK's own 5 s default, as on 2026-11-18 with about 40 orders that day."""


@pytest.mark.parametrize("simulation", [True, False], ids=["simulation", "production"])
async def test_a_statement_on_a_busy_day_refreshes_the_days_orders_once_within_the_status_timeout(simulation: bool) -> None:
    client = FakeShioaji(simulation=simulation)
    broker = provider(client)
    await broker.place_order(order(quantity=1000), no_refusal, asyncio.Event())
    client.account_refreshes.clear()
    client.account_refresh_milliseconds = BUSY_DAY_MILLISECONDS

    statement = await broker.statement(date(2026, 7, 21), date(2026, 10, 19))

    assert client.account_refreshes == [round(CONFIG.shioaji.status_timeout_seconds * 1000)] == [30_000]
    assert [(fill.stock_id, fill.quantity, fill.price) for fill in statement.fills] == [("2330", 1000, 100.0)]
    expected_cash = CONFIG.shioaji.simulation_initial_cash - 100_000 - COSTS.apply(TradeAction.BUY, "2330", 100.0, 1000, now=NOW).fee
    assert statement.balance == (expected_cash if simulation else 1_000_000)


@pytest.mark.parametrize("simulation", [True, False], ids=["simulation", "production"])
async def test_the_cash_read_before_an_order_on_a_busy_day_waits_the_status_timeout_and_the_order_is_sent(simulation: bool) -> None:
    client = FakeShioaji(simulation=simulation, account_refresh_milliseconds=BUSY_DAY_MILLISECONDS)
    broker = provider(client)

    account = await broker.get_account()
    placed = await broker.place_order(order(quantity=1000), no_refusal, asyncio.Event())

    assert account.cash > 0 and client.account_refreshes == [30_000, 30_000]
    assert (placed.status, len(client.placed)) == (OrderStatus.FILLED, 1)


async def test_an_account_slower_than_the_status_timeout_fails_the_statement_and_the_order_saying_only_the_error_type() -> None:
    client = FakeShioaji(account_refresh_milliseconds=30_001)
    broker = provider(client)

    with pytest.raises(BrokerNotAnswering, match="^Shioaji answered TimeoutError$") as refused:
        await broker.statement(date(2026, 7, 21), date(2026, 10, 19))
    failed = await broker.place_order(order(), no_refusal, asyncio.Event())

    assert (failed.status, client.placed, client.account_refreshes) == (OrderStatus.FAILED, [], [30_000, 30_000])
    assert failed.reason == "BrokerNotAnswering: Shioaji answered TimeoutError"
    assert "in time" not in raised(refused.value), "the server's words stay out"


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
    client = FakeShioaji(simulation=False, balance=AccountBalance(acc_balance=150_000.0, date="2026-10-19", errmsg=""))
    broker = provider(client)

    first = await broker.place_order(order(quantity=1000, price=100.0), no_refusal, asyncio.Event())
    second = await broker.place_order(order(quantity=1000, price=100.0), no_refusal, asyncio.Event())

    assert (first.status, second.status, len(client.placed)) == (OrderStatus.FILLED, OrderStatus.REJECTED, 1)
    assert second.reason == "INSUFFICIENT_CASH: needs 100,142 including fee, cash is 49,858"


async def test_fills_and_cancels_are_read_back_from_the_trade_list_when_place_order_returned_a_copy() -> None:
    client = FakeShioaji(
        scripts={StockOrderLot.Common: [Report(Status.Submitted), Report(Status.PartFilled, ((100.0, 1),))]}, updates_in_place=False
    )

    placed = await provider(client).place_order(order(quantity=2000), no_refusal, asyncio.Event())

    assert (placed.status, placed.filled_quantity, len(client.cancelled)) == (OrderStatus.CANCELLED, 1000, 1)


async def test_an_order_whose_deals_lag_its_dealt_quantity_fails_instead_of_under_recording() -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.Cancelled, ((100.0, 1),), deal_quantity=2)]})

    placed = await provider(client).place_order(order(quantity=3000), no_refusal, asyncio.Event())

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
    client: FakeShioaji, monkeypatch: pytest.MonkeyPatch, logger: RecordingLogger, server: ShioajiServer
) -> IExecutionProvider | None:
    """The SinoPac broker connect_shioaji builds on `client` at the start of a personal site on `server`, or None."""
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: client)
    polling = CONFIG.shioaji.model_copy(update={"poll_interval_seconds": 0, "max_polls": 3})
    site = sinopac_setup(CONFIG.model_copy(update={"shioaji": polling}), server)
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

    assert await broker_of(client, monkeypatch, logger, ShioajiServer.PRODUCTION) is None
    assert any(says in line and "SinoPac Production orders unavailable" in line for line in said(logger))
    assert private_parts(*said(logger)) == []


SIMULATION_READS = ("update_status", "list_trades", "list_positions", "list_profit_loss")
"""What an account read asks the simulation server, which reports no balance and no settlement."""

PRODUCTION_READS = ("account_balance", "settlements", "update_status", "list_trades", "list_positions")


@pytest.mark.parametrize(
    ("client", "says"),
    [
        *[(FakeShioaji(refusals={read: sdk_refusal()}), "Shioaji answered TokenError, status 401") for read in SIMULATION_READS],
        *[
            (FakeShioaji(simulation=False, refusals={read: sdk_refusal()}), "Shioaji answered TokenError, status 401")
            for read in PRODUCTION_READS
        ],
        (
            FakeShioaji(simulation=False, balance=AccountBalance(acc_balance=1_000_000.0, date="2026-10-19", errmsg=SERVER_WORDS)),
            "account balance",
        ),
    ],
    ids=[
        *(f"simulation {read}" for read in SIMULATION_READS),
        *(f"production {read}" for read in PRODUCTION_READS),
        "balance with an error message",
    ],
)
async def test_a_refused_account_read_raises_and_fails_the_order_saying_only_the_error_type_and_status(
    client: FakeShioaji, says: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = RecordingLogger()
    server = ShioajiServer.SIMULATION if client.simulation else ShioajiServer.PRODUCTION
    broker = await broker_of(client, monkeypatch, logger, server)
    assert broker is not None

    with pytest.raises(Exception) as refused:
        await broker.get_account()
    failed = await broker.place_order(order(), no_refusal, asyncio.Event())

    assert (failed.status, client.placed) == (OrderStatus.FAILED, [])
    assert says in str(refused.value) and failed.reason is not None and says in failed.reason
    assert private_parts(raised(refused.value), failed.reason, *said(logger)) == []


async def test_an_order_whose_answer_was_lost_and_whose_lookups_failed_says_only_the_error_types_and_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeShioaji(
        place_error=sdk_refusal(),
        place_error_after_accepting=True,
        refusals={"update_status": sdk_refusal()},
        refuses_once_placed=True,
    )
    logger = RecordingLogger()

    failed = await (await broker_of(client, monkeypatch, logger, ShioajiServer.SIMULATION)).place_order(
        order(), no_refusal, asyncio.Event()
    )

    tag = f"{failed.id.hex[:5]}0"
    assert failed.status == OrderStatus.UNCONFIRMED
    assert [message for message in said(logger) if "lookup" in message or "did not confirm" in message] == [
        f"Shioaji did not confirm the order tagged {tag} (Shioaji answered TokenError, status 401): "
        "it is looked for in the account's orders",
        *[f"Shioaji lookup of the order tagged {tag} failed: Shioaji answered TokenError, status 401"] * 3,
    ]
    assert private_parts(failed.reason, *said(logger)) == []


async def test_refused_status_reads_and_cancel_are_logged_saying_only_the_error_type_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeShioaji(refusals={"update_status": sdk_refusal(), "cancel_order": sdk_refusal()}, refuses_once_placed=True)
    logger = RecordingLogger()

    unread = await (await broker_of(client, monkeypatch, logger, ShioajiServer.SIMULATION)).place_order(
        order(), no_refusal, asyncio.Event()
    )

    assert unread.status == OrderStatus.UNCONFIRMED
    assert [message for message in said(logger) if "failed:" in message] == [
        *["Shioaji status refresh failed: Shioaji answered TokenError, status 401"] * 3,
        f"Shioaji cancel of the order tagged {unread.id.hex[:5]}0 failed: Shioaji answered TokenError, status 401",
        *["Shioaji status refresh failed: Shioaji answered TokenError, status 401"] * 3,
    ]
    assert private_parts(unread.reason, *said(logger)) == []


async def test_a_refused_exchange_order_gives_the_brokers_status_code_instead_of_its_message(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeShioaji(scripts={StockOrderLot.Common: [Report(Status.Failed, msg=SERVER_WORDS, status_code="88")]})
    logger = RecordingLogger()

    refused = await (await broker_of(client, monkeypatch, logger, ShioajiServer.SIMULATION)).place_order(
        order(), no_refusal, asyncio.Event()
    )

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

    placed = await provider(client).place_order(order(quantity=1500), refusing_from(1), asyncio.Event())

    assert client.placed == []
    assert (placed.status, placed.filled_quantity) == (OrderStatus.REJECTED, 0)
    assert placed.reason == f"{RejectReason.ORDERING_OFF.name}: {ORDERING_OFF[1]}"


async def test_ordering_turned_off_between_the_parts_stops_the_odd_lot_and_the_order_says_why() -> None:
    client = FakeShioaji()

    placed = await provider(client).place_order(order(quantity=1500), refusing_from(2), asyncio.Event())

    assert [(trade.order.order_lot, trade.order.quantity) for trade in client.placed] == [(StockOrderLot.Common, 1)]
    assert (placed.status, placed.filled_quantity) == (OrderStatus.CANCELLED, 1000)
    assert placed.reason is not None and f"the rest was not sent: {ORDERING_OFF[1]}" in placed.reason


STARTING_CASH = CONFIG.shioaji.simulation_initial_cash


async def test_on_the_simulation_server_the_cash_is_figured_from_the_starting_cash_and_the_brokers_own_records() -> None:
    """Measured on 2026-11-17: the simulation server answers the balance with 0 and no error, and lists no settlement."""
    client = FakeShioaji(
        holdings=[position("2330", 1500, 95.5), position("2603", 2000, 50.0)],
        profit_losses=[sale("2317", 1000, 58.0, -2_300.0, "2026-10-09"), sale("1101", 37, 35.0, 410.0, "2019-03-04")],
    )

    account = await provider(client).get_account()

    assert account.cash == STARTING_CASH - 1500 * 95.5 - 2000 * 50.0 - 2_300.0 + 410.0
    assert [(begin, unit) for begin, _, unit in client.profit_loss_requests] == [("1970-01-01", Unit.Share)]
    assert client.bank_reads == []


async def test_a_production_session_reads_the_brokers_balance_and_never_the_figure_from_the_starting_cash() -> None:
    """The same records on the production server: the cash is the bank's, however much the starting cash would leave."""
    client = FakeShioaji(
        simulation=False,
        balance=AccountBalance(acc_balance=30_000.0, date="2026-10-19", errmsg=""),
        holdings=[position("2603", 2000, 50.0)],
        profit_losses=[sale("2317", 1000, 58.0, 5_000.0, "2026-10-09")],
    )
    broker = provider(client)

    account = await broker.get_account()
    refused = await broker.place_order(order(quantity=1000, price=100.0), no_refusal, asyncio.Event())

    assert (account.cash, client.profit_loss_requests) == (30_000.0, [])
    assert (refused.status, client.placed) == (OrderStatus.REJECTED, [])
    assert refused.reason == "INSUFFICIENT_CASH: needs 100,142 including fee, cash is 30,000"


@pytest.mark.parametrize("listed_at_once", [False, True], ids=["the positions lag", "the positions list the fill at once"])
async def test_on_the_simulation_server_buys_in_a_row_never_spend_the_same_cash_twice(listed_at_once: bool) -> None:
    """After the positions the cash is 250,000: two BUYs of 100,142 fit and the third does not, however the broker lists a fill."""
    client = FakeShioaji(holdings=[position("2603", 15_000, 50.0)])
    client.Contracts.Stocks = FakeStocks({code: stock(code) for code in ("2330", "2317", "2454")})
    broker = provider(client)
    placed = []

    for code in ("2330", "2317", "2454"):
        placed.append(await broker.place_order(order(quantity=1000, price=100.0, stock_id=code), no_refusal, asyncio.Event()))

        if listed_at_once and placed[-1].status == OrderStatus.FILLED:
            client.holdings.append(position(code, 1000, 100.0, held_yesterday=0))

    assert [buy.status for buy in placed] == [OrderStatus.FILLED, OrderStatus.FILLED, OrderStatus.REJECTED]
    assert placed[-1].reason == "INSUFFICIENT_CASH: needs 100,142 including fee, cash is 49,716"
    assert (await broker.get_account()).cash == STARTING_CASH - 15_000 * 50.0 - 2 * 100_142


@pytest.mark.parametrize("listed", [False, True], ids=["the position does not list it yet", "the position lists it"])
async def test_on_the_simulation_server_a_buy_of_a_stock_held_since_yesterday_is_spent_once(listed: bool) -> None:
    """A later run of the same day reads the account after an earlier run's BUY of 1000 more of a stock held since yesterday."""
    client = FakeShioaji(holdings=[position("2330", 3000, 100.0)])
    broker = provider(client)
    bought = await broker.place_order(order(quantity=1000, price=100.0), no_refusal, asyncio.Event())

    if listed:
        client.holdings = [position("2330", 4000, (3000 * 100.0 + 100_142) / 4000, held_yesterday=3000)]

    assert bought.status == OrderStatus.FILLED
    assert (await broker.get_account()).cash == pytest.approx(STARTING_CASH - 3000 * 100.0 - 100_142)


async def test_the_simulation_cash_starts_at_its_own_setting_and_not_at_the_mock_accounts() -> None:
    config = CONFIG.model_copy(
        update={
            "mock_trading": CONFIG.mock_trading.model_copy(update={"initial_cash": 5_000_000.0}),
            "shioaji": CONFIG.shioaji.model_copy(update={"simulation_initial_cash": 2_000_000.0}),
        }
    )
    client = FakeShioaji()
    client.stock_account = client.account_at_login
    broker = ShioajiExecutionProvider(
        connection=ShioajiConnection(client=client, up=True),
        login=login_of(simulation=True),
        config=config,
        market_clock=TaiwanMarketClock(config.market_hours),
        logger=SilentLogger(),
    )

    assert (await broker.get_account()).cash == 2_000_000


async def test_on_the_simulation_server_the_statements_balance_is_the_same_figure_as_the_accounts_cash() -> None:
    client = FakeShioaji(holdings=[position("2330", 1500, 95.5)], profit_losses=[sale("2317", 1000, 58.0, -2_300.0, "2025-01-09")])
    broker = provider(client)

    statement = await broker.statement(date(2026, 7, 21), date(2026, 10, 19))

    assert (statement.simulation, statement.balance) == (True, STARTING_CASH - 1500 * 95.5 - 2_300.0)
    assert (statement.balance, statement.sales) == ((await broker.get_account()).cash, [])


async def test_records_that_spent_more_than_the_starting_cash_count_as_no_cash_and_say_so() -> None:
    client, logger = FakeShioaji(holdings=[position("2330", 11_000, 100.0)]), RecordingLogger()
    broker = provider(client, logger=logger)

    account = await broker.get_account()

    assert account.cash == 0
    assert [message for level, message in logger.records if level == "warning"] == [
        "Shioaji simulation cash is -100,000 by the broker's records and shioaji.simulation_initial_cash 1,000,000: counted "
        "as no cash. The setting is under what the account spent."
    ]
