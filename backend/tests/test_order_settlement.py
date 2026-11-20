"""
SinoPac orders whose outcome the site could not read when they were sent (UNCONFIRMED), settled from SinoPac's own
record of the day: by a run on SinoPac before it sends anything and at its end, and by the Web API's timer, on the real
adapter over a fake client on the simulation server. Found live on 2026-11-19: a BUY of 3029 whose answer the SDK
stopped waiting for was listed a second after the adapter's one lookup, dealt all 430 shares while nothing watched it
and stayed in the journal as FAILED 0/430.
"""

import asyncio
from dataclasses import replace
from datetime import datetime, time, timedelta
from uuid import UUID

import pytest
from shioaji.constant import Action, OrderType as BrokerTimeInForce, Status, StockOrderCond, StockOrderLot, StockPriceType
from shioaji.error import TimeoutError as ShioajiTimeoutError
from shioaji.order import Order as BrokerOrder
from support.fake_shioaji import DONE, FakeContracts, FakeShioaji, FakeStocks, Report, stock
from support.fakes import FakeTradingJournal
from support.harness import ADMINISTRATOR, MARKET_OPEN, CliHarness, build_harness, harness_config, runtime_for
from support.settings import sinopac_setup
from trading_stack import analysed_stock, bar

from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.order import Order
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import (
    ExecutionProvider,
    OrderStatus,
    OrderType,
    RejectReason,
    Role,
    ShioajiServer,
    TimeInForce,
    TradeAction,
    Workflow,
)
from a_domain.types.ids import UserId, new_decision_id
from c_infrastructure.market.shioaji_quote_provider import ShioajiConnection
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE
from c_infrastructure.trading.shioaji import execution_provider
from c_infrastructure.trading.shioaji.execution_provider import ShioajiExecutionProvider
from d_presentation.web.scheduled_follows import settle_users_orders

pytestmark = pytest.mark.asyncio

DAILY_LIMIT = 0.15
"""
trading.max_daily_buy_equity_pct here: 150,000 of the simulation account's 1,000,000, so an earlier BUY of 100,000 counted
in full leaves no room for a second, 102,000 at its limit.
"""


@pytest.fixture(autouse=True)
def no_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    async def wait(seconds: float) -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(execution_provider, "sleep", wait)


def sinopac_site(client: FakeShioaji) -> CliHarness:
    """An administrator's site whose SinoPac is the real adapter over `client` on the simulation server, at Monday 10:00."""
    config = sinopac_setup(harness_config(), ShioajiServer.SIMULATION)
    config = config.model_copy(update={"trading": config.trading.model_copy(update={"max_daily_buy_equity_pct": DAILY_LIMIT})})
    harness = build_harness(config=config, sinopac=True)
    client.stock_account = client.account_at_login
    login = config.shioaji.login()
    assert login is not None
    adapter = ShioajiExecutionProvider(ShioajiConnection(client=client, up=True), login, config, harness.clock, harness.logger)
    dependencies = replace(harness.dependencies, real_broker=adapter)
    runtime = runtime_for(replace(harness, dependencies=dependencies), config)
    runtime.become_current()
    harness = replace(harness, dependencies=dependencies, runtime=runtime)
    harness.prices.realtime["2330"] = bar(MARKET_OPEN - timedelta(minutes=1), 100.0)
    return harness


def unconfirmed_buy(
    harness: CliHarness,
    *,
    ended: bool = True,
    sent_at: datetime = MARKET_OPEN - timedelta(minutes=30),
    journal: ITradingJournal | None = None,
    submitted: bool = False,
    pending_at: float | None = None,
) -> Order:
    """
    A SinoPac BUY of 1000 at 100 of an earlier manual BUY run, the administrator's unless another `journal` holds it,
    whose answer was lost; `submitted`, one whose answer came, of a run whose process stopped before its end;
    `pending_at`, one still PENDING at that limit, as its journal row was saved before the adapter moved the limit
    into the day's price band and sent it, of a run whose process stopped before it saved the answer.
    """
    run = SystemStats(workflow=Workflow.MANUAL_BUY, execution_provider=ExecutionProvider.SHIOAJI, start_time=sent_at)
    run.end_time = sent_at + timedelta(minutes=1) if ended else None
    order = Order(
        run_id=run.run_id,
        decision_id=new_decision_id(),
        stock_id="2330",
        action=TradeAction.BUY,
        order_type=OrderType.LIMIT,
        quantity=1000,
        limit_price=pending_at or 100.0,
        price_at_signal=100.0,
        time_in_force=TimeInForce.IOC,
        created_at=sent_at,
        updated_at=sent_at,
    )
    if submitted:
        order.submit(now=sent_at)
    elif pending_at is None:
        order.leave_unconfirmed(
            f"unconfirmed at Shioaji: Common 1000 shares tagged {order.id.hex[:5]}0, which Shioaji does not list", now=sent_at
        )

    journal = journal or harness.journal
    assert isinstance(journal, FakeTradingJournal)
    journal.runs[run.run_id] = run
    journal.orders[order.id] = order
    return order


def listed_at_sinopac(client: FakeShioaji, order: Order, report: Report, quantity: int = 1) -> None:
    """
    The exchange order SinoPac holds for the order's one board lot, under its tag, as `report` says at its next read;
    `quantity` lots, as sent unless the test says otherwise.
    """
    client.scripts = {StockOrderLot.Common: [report]}
    broker_order = BrokerOrder(
        price=100.0,
        quantity=quantity,
        action=Action.Buy,
        price_type=StockPriceType.LMT,
        order_type=BrokerTimeInForce.IOC,
        order_lot=StockOrderLot.Common,
        order_cond=StockOrderCond.Cash,
        account=client.stock_account,
        custom_field=f"{order.id.hex[:5]}0",
    )
    client.place_order(client.Contracts.Stocks["2330"], broker_order)
    client.scripts = {}


def journaled_ids(harness: CliHarness) -> set[UUID]:
    journal = harness.journal
    assert isinstance(journal, FakeTradingJournal)
    return set(journal.orders)


def journaled(harness: CliHarness, order: Order) -> Order:
    journal = harness.journal
    assert isinstance(journal, FakeTradingJournal)
    return journal.orders[order.id]


@pytest.mark.parametrize(
    ("report", "earlier", "next_buy"),
    [
        (Report(Status.Cancelled), (OrderStatus.CANCELLED, 0), OrderStatus.FILLED),
        (Report(Status.Filled, ((100.0, 1),)), (OrderStatus.FILLED, 1000), OrderStatus.REJECTED),
    ],
    ids=["it dealt nothing", "it dealt in full"],
)
async def test_a_run_on_sinopac_first_settles_an_earlier_runs_unconfirmed_buy_so_the_days_limit_counts_what_sinopac_did(
    report: Report, earlier: tuple[OrderStatus, int], next_buy: OrderStatus
) -> None:
    client = FakeShioaji()
    harness = sinopac_site(client)
    lost = unconfirmed_buy(harness)
    listed_at_sinopac(client, lost, report)

    status = await harness.runtime.pipeline_for(ADMINISTRATOR, ExecutionProvider.SHIOAJI).buy_manually(analysed_stock(), 1000)

    settled, [bought] = journaled(harness, lost), status.orders
    assert (settled.status, settled.filled_quantity) == earlier
    assert bought.status == next_buy
    assert next_buy == OrderStatus.FILLED or (bought.reason or "").startswith(RejectReason.DAILY_BUY_LIMIT.name)


async def test_a_buy_on_sinopac_is_refused_while_an_earlier_buy_of_the_stock_awaits_settlement() -> None:
    client = FakeShioaji()
    harness = sinopac_site(client)
    lost = unconfirmed_buy(harness)

    status = await harness.runtime.pipeline_for(ADMINISTRATOR, ExecutionProvider.SHIOAJI).buy_manually(analysed_stock(), 1000)

    [refused] = status.orders
    assert (journaled(harness, lost).status, refused.status, client.placed) == (OrderStatus.UNCONFIRMED, OrderStatus.REJECTED, [])
    assert (refused.reason or "").startswith(f"{RejectReason.UNSETTLED_BUY.name}: order {lost.id}, an earlier BUY of 2330 today")


async def test_a_buy_on_sinopac_is_refused_while_an_earlier_buy_of_the_stock_a_stopped_process_left_is_still_open() -> None:
    """In a CLI session, or in the Web API before its timer ended the run, the BUY a stopped process left is still SUBMITTED."""
    client = FakeShioaji()
    harness = sinopac_site(client)
    started = harness.dependencies.process_started
    left = unconfirmed_buy(harness, ended=False, sent_at=started - timedelta(minutes=5), submitted=True)

    status = await harness.runtime.pipeline_for(ADMINISTRATOR, ExecutionProvider.SHIOAJI).buy_manually(analysed_stock(), 400)

    [refused] = status.orders
    assert (journaled(harness, left).status, refused.status, client.placed) == (OrderStatus.SUBMITTED, OrderStatus.REJECTED, [])
    assert (refused.reason or "").startswith(f"{RejectReason.UNSETTLED_BUY.name}: order {left.id}, an earlier BUY of 2330 today")


async def test_a_buy_sinopac_lists_only_after_the_first_look_is_settled_at_the_end_of_its_own_run() -> None:
    client = FakeShioaji(
        place_error=ShioajiTimeoutError("place_order", {}),
        place_error_after_accepting=True,
        unlisted_refreshes=harness_config().shioaji.max_polls,
    )
    harness = sinopac_site(client)

    status = await harness.runtime.pipeline_for(ADMINISTRATOR, ExecutionProvider.SHIOAJI).buy_manually(analysed_stock(), 1000)

    [sent] = status.orders
    assert (sent.status, sent.filled_quantity, sent.average_filled_price) == (OrderStatus.FILLED, 1000, 100.0)
    assert journaled(harness, sent) == sent
    assert all(trade.status.status in DONE for trade in client.placed)


async def test_the_timer_settles_ended_runs_only_and_fails_what_sinopac_never_listed_by_the_days_end_then_asks_nothing_more() -> None:
    client = FakeShioaji()
    harness = sinopac_site(client)
    never_listed, in_flight = unconfirmed_buy(harness), unconfirmed_buy(harness, ended=False)
    listed_at_sinopac(client, in_flight, Report(Status.Submitted))

    await settle_users_orders(harness.runtime)

    assert [journaled(harness, order).status for order in (never_listed, in_flight)] == [OrderStatus.UNCONFIRMED] * 2
    assert client.cancelled == [], "a run still under way keeps its part"

    harness.clock.current_time = datetime.combine(MARKET_OPEN.date(), time(15, 0), TAIWAN_TIMEZONE)
    await settle_users_orders(harness.runtime)
    refreshes = list(client.account_refreshes)
    await settle_users_orders(harness.runtime)

    failed = journaled(harness, never_listed)
    assert (failed.status, failed.filled_quantity) == (OrderStatus.FAILED, 0)
    assert failed.reason is not None and failed.reason.startswith("Shioaji never listed it by its session's end")
    assert (journaled(harness, in_flight).status, client.cancelled) == (OrderStatus.UNCONFIRMED, [])
    assert client.account_refreshes == refreshes, "nothing left to settle, so SinoPac is not asked again"


async def test_an_order_of_an_earlier_day_is_not_looked_up_in_todays_record_and_fails() -> None:
    client = FakeShioaji()
    harness = sinopac_site(client)
    friday = unconfirmed_buy(harness, sent_at=MARKET_OPEN - timedelta(days=3))
    listed_at_sinopac(client, friday, Report(Status.Filled, ((100.0, 1),)))

    await settle_users_orders(harness.runtime)

    settled = journaled(harness, friday)
    assert (settled.status, settled.filled_quantity, client.account_refreshes) == (OrderStatus.FAILED, 0, [])


@pytest.mark.parametrize("login", ["down", "missing"], ids=["the login down", "no real broker"])
async def test_an_order_of_an_earlier_day_fails_without_the_login_so_it_no_longer_holds_back_a_switch_of_the_server(
    login: str,
) -> None:
    """SinoPac's record of an earlier day is gone whatever the login, so its order needs no login to fail."""
    client = FakeShioaji()
    harness = sinopac_site(client)
    config = harness.runtime.config
    site_login = config.shioaji.login()
    assert site_login is not None
    down = ShioajiExecutionProvider(ShioajiConnection(client=client, up=False), site_login, config, harness.clock, harness.logger)
    dependencies = replace(harness.dependencies, real_broker=down if login == "down" else None)
    friday, today = unconfirmed_buy(harness, sent_at=MARKET_OPEN - timedelta(days=3)), unconfirmed_buy(harness)

    await settle_users_orders(runtime_for(replace(harness, dependencies=dependencies), config))

    failed = journaled(harness, friday)
    assert (failed.status, failed.filled_quantity) == (OrderStatus.FAILED, 0)
    assert failed.reason == (
        f"SinoPac no longer lists the orders of 2026-10-16, so what the parts tagged {friday.id.hex[:5]}0 did there cannot be "
        "read: check SinoPac's order history; 0 of 1000 shares were recorded filled"
    )
    assert journaled(harness, today).status == OrderStatus.UNCONFIRMED, "today's order waits for the login"
    assert await dependencies.users_orders.awaiting_settlement(ExecutionProvider.SHIOAJI) == 1
    assert client.account_refreshes == []


async def test_a_listed_order_of_the_tag_and_stock_that_differs_in_another_field_is_not_the_part_and_is_logged() -> None:
    """Whether SinoPac keeps an order's quantity and price as sent after a partial deal or a cancel is not verified yet."""
    client = FakeShioaji()
    harness = sinopac_site(client)
    lost = unconfirmed_buy(harness)
    listed_at_sinopac(client, lost, Report(Status.Cancelled), quantity=2)

    await settle_users_orders(harness.runtime)

    tag = f"{lost.id.hex[:5]}0"
    warned = [message for level, message in harness.logger.records if level == "warning" and tag in message]
    assert journaled(harness, lost).status == OrderStatus.UNCONFIRMED
    assert warned == [
        f"Shioaji lists an order tagged {tag} of 2330 whose quantity is 2 where 1 was sent: it is not taken as that part"
    ]


async def test_the_timer_ends_a_sinopac_run_an_earlier_process_left_and_settles_its_open_orders_but_never_this_processs_runs() -> None:
    client = FakeShioaji()
    harness = sinopac_site(client)
    started = harness.dependencies.process_started
    left = unconfirmed_buy(harness, ended=False, sent_at=started - timedelta(minutes=5), submitted=True)
    running = unconfirmed_buy(harness, ended=False, sent_at=started + timedelta(minutes=5), submitted=True)
    listed_at_sinopac(client, left, Report(Status.Filled, ((100.0, 1),)))

    await settle_users_orders(harness.runtime)

    journal = harness.journal
    assert isinstance(journal, FakeTradingJournal)
    ended = journal.runs[left.run_id]
    assert (ended.end_time, ended.failure) == (harness.clock.now(), "the process that ran it stopped before the run ended")
    assert (journaled(harness, left).status, journaled(harness, left).filled_quantity) == (OrderStatus.FILLED, 1000)
    assert (journal.runs[running.run_id].end_time, journaled(harness, running).status) == (None, OrderStatus.SUBMITTED)


async def test_a_part_sent_at_the_days_limit_up_is_settled_also_after_its_process_stopped_before_it_saved_the_send() -> None:
    """
    Decided at 100, the BUY's limit is 102, past the day's limit-up of 100, so the adapter sent it at 100. The process
    stopped before it saved that, and its journal row still says 102 and PENDING: settlement finds the part by the
    limit the band allowed, as it was sent.
    """
    client = FakeShioaji()
    harness = sinopac_site(client)
    started = harness.dependencies.process_started
    session = harness.clock.to_trading_date(started - timedelta(minutes=5))
    client.Contracts = FakeContracts(FakeStocks({"2330": stock("2330", 100 / 1.1, session)}))
    left = unconfirmed_buy(harness, ended=False, sent_at=started - timedelta(minutes=5), pending_at=102.0)
    listed_at_sinopac(client, left, Report(Status.Filled, ((100.0, 1),)))

    await settle_users_orders(harness.runtime)

    settled = journaled(harness, left)
    assert client.Contracts.Stocks["2330"].limit_up == 100.0
    assert (settled.status, settled.filled_quantity, settled.limit_price) == (OrderStatus.FILLED, 1000, 100.0)


async def test_the_timer_settles_the_sinopac_orders_of_a_user_who_may_no_longer_hold_sinopac_in_that_users_journal_alone() -> None:
    client = FakeShioaji()
    harness = sinopac_site(client)
    demoted = replace(ADMINISTRATOR, user_id=UserId("demoted"), username="demoted", email="demoted@example.com", role=Role.USER)
    harness.users.add(demoted, "a password")
    theirs = harness.dependencies.owned_ports(demoted).journal
    lost = unconfirmed_buy(harness, journal=theirs)
    listed_at_sinopac(client, lost, Report(Status.Filled, ((100.0, 1),)))

    await settle_users_orders(harness.runtime)

    assert isinstance(theirs, FakeTradingJournal)
    assert (theirs.orders[lost.id].status, theirs.orders[lost.id].filled_quantity) == (OrderStatus.FILLED, 1000)
    assert lost.id not in journaled_ids(harness), "the administrator's journal holds nothing of it"


async def test_a_settlement_logs_an_order_at_info_only_when_its_status_changes() -> None:
    client = FakeShioaji()
    harness = sinopac_site(client)
    waiting, dealt = unconfirmed_buy(harness), unconfirmed_buy(harness)
    listed_at_sinopac(client, dealt, Report(Status.Filled, ((100.0, 1),)))

    await settle_users_orders(harness.runtime)

    settled = [message for level, message in harness.logger.records if level == "info" and "settled" in message]
    assert [str(dealt.id) in message for message in settled] == [True]
    assert journaled(harness, waiting).status == OrderStatus.UNCONFIRMED


async def test_the_settlements_of_sinopac_in_one_process_run_one_at_a_time() -> None:
    client = FakeShioaji()
    harness = sinopac_site(client)
    unconfirmed_buy(harness)

    async with harness.dependencies.settlement_locks[ExecutionProvider.SHIOAJI]:
        timer = asyncio.create_task(settle_users_orders(harness.runtime))

        for _ in range(20):
            await asyncio.sleep(0)

        assert client.account_refreshes == [], "the timer waits while a run's settlement holds SinoPac"

    await timer
    assert len(client.account_refreshes) == 1
