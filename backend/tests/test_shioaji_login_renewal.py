"""
The site's Shioaji login made again on a new client: at the first use after Shioaji refused its token, at the first
use from the market day's shioaji.login_renewal_time on, and no sooner than shioaji.login_retry_seconds after a login
failed. The new login takes effect for the next run and read: a run under way keeps the client it started on, and
SinoPac's record of the day settles on the new one what the earlier one sent.
"""

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import shioaji
from shioaji.constant import Status
from shioaji.error import TokenError
from support.fake_shioaji import FakeContracts, FakeShioaji, FakeStocks, Report, same_account, snapshot, stock
from support.fakes import FakeTradingJournal, RecordingLogger
from support.harness import ADMINISTRATOR, CliHarness, build_harness, harness_config, runtime_for
from support.settings import sinopac_setup
from test_order_settlement import listed_at_sinopac, unconfirmed_buy
from test_runtime_lifetime import edit, shioaji_test_config, switch_project
from trading_stack import SilentLogger, analysed_stock, bar

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.types.enums import ExecutionProvider, OrderStatus, ShioajiServer
from b_application.config.app_config import AppConfig
from c_infrastructure.market.shioaji_quote_provider import ShioajiConnection, ShioajiQuoteProvider
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock
from c_infrastructure.trading.shioaji import execution_provider
from c_infrastructure.trading.shioaji.execution_provider import ShioajiExecutionProvider
from d_presentation.dependencies import ProcessState, Runtime, get_project_root, open_runtime
from d_presentation.live_runtime import RuntimeSwitch
from d_presentation.web.scheduled_follows import settle_users_orders
from d_presentation.web.session import request_hold

pytestmark = pytest.mark.asyncio

FRIDAY_10_00 = datetime(2026, 11, 13, 10, 0, tzinfo=TAIWAN_TIMEZONE)
MONDAY_10_00 = datetime(2026, 11, 16, 10, 0, tzinfo=TAIWAN_TIMEZONE)


@pytest.fixture(autouse=True)
def no_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    async def wait(seconds: float) -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(execution_provider, "sleep", wait)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """The market clock of every runtime the test opens: Monday 10:00 unless the test moves it."""
    now = [MONDAY_10_00]
    monkeypatch.setattr(TaiwanMarketClock, "now", lambda self: now[0])
    return now


LOGIN_REFUSALS: list[Exception] = []
"""What the next client's login raises, while the test holds one here."""

LOGIN_GATES: list[threading.Event] = []
"""What the next client's login waits for in its thread, while the test holds one here: a SinoPac slow to answer."""


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch, clock: list[datetime]) -> list[FakeShioaji]:
    """Every Shioaji client a runtime makes, each answering 2330's last trade a minute before it was made."""
    made: list[FakeShioaji] = []
    LOGIN_REFUSALS.clear()
    LOGIN_GATES.clear()

    def client(simulation: bool) -> FakeShioaji:
        traded = snapshot("2330", clock[0] - timedelta(minutes=1), 101.0, 10)
        contracts, refusal = FakeContracts(FakeStocks({"2330": stock("2330")})), LOGIN_REFUSALS[0] if LOGIN_REFUSALS else None
        gate = LOGIN_GATES[0] if LOGIN_GATES else None
        made.append(
            FakeShioaji(simulation, Contracts=contracts, snapshot_answers={"2330": traded}, login_error=refusal, login_gate=gate)
        )
        return made[-1]

    monkeypatch.setattr(shioaji, "Shioaji", client)
    return made


@asynccontextmanager
async def site(config: AppConfig, logger: RecordingLogger, project: Path | None = None) -> AsyncIterator[RuntimeSwitch]:
    """The process's runtimes, the first opened on `config`, each later one as the switch opens it."""
    shared = ProcessState(logger=logger, attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())
    switch = RuntimeSwitch(lambda candidate: open_runtime(candidate, shared), project or get_project_root(), logger)
    await switch.start(config)

    try:
        yield switch
    finally:
        await switch.close()


async def page_quote(switch: RuntimeSwitch) -> Ohlcv | None:
    """What a page's request for 2330's realtime quote answers: the request's hold of a runtime, then its one call."""
    hold = request_hold(switch)
    opened = await anext(hold)

    try:
        answer = await opened.runtime.signed_out.load_page_quotes(["2330"], [])
    finally:
        await hold.aclose()

    return answer.quotes.get("2330")


def logins(clients: list[FakeShioaji]) -> list[tuple[int, int]]:
    return [(len(client.logins), client.logouts) for client in clients]


async def test_a_refused_token_answers_no_quote_and_the_next_request_logs_in_again_on_a_new_client_and_answers(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shioaji answered TokenError at 09:05 on 2026-11-20 to a login 26 hours old, and the site kept asking it."""
    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger()) as switch:
        clients[0].market_data_error = TokenError(401, "token expired")
        refused = await page_quote(switch)
        answered = await page_quote(switch)

    assert refused is None and answered is not None and answered.close == 101.0
    assert logins(clients) == [(1, 0), (1, 0)], "the refused client is kept, never logged out"
    assert [len(client.snapshot_requests) for client in clients] == [0, 1]


@pytest.mark.parametrize(
    ("asked_at", "logged_in_again"),
    [
        (datetime(2026, 11, 14, 10, 0, tzinfo=TAIWAN_TIMEZONE), False),
        (datetime(2026, 11, 16, 8, 14, tzinfo=TAIWAN_TIMEZONE), False),
        (datetime(2026, 11, 16, 8, 15, tzinfo=TAIWAN_TIMEZONE), True),
    ],
    ids=["saturday", "monday-before-the-renewal-time", "monday-at-the-renewal-time"],
)
async def test_a_login_made_on_a_market_day_is_made_again_at_the_first_request_from_the_next_market_days_renewal_time(
    asked_at: datetime,
    logged_in_again: bool,
    clients: list[FakeShioaji],
    clock: list[datetime],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Friday's login serves through the weekend. Monday's first request from 08:15 logs in again, and the session's quote
    is the new login's.
    """
    clock[0] = FRIDAY_10_00

    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger()) as switch:
        clock[0] = asked_at
        await page_quote(switch)
        made_at_the_request = len(clients)
        clock[0] = MONDAY_10_00
        answered = await page_quote(switch)

    assert made_at_the_request == (2 if logged_in_again else 1)
    assert len(clients) == 2 and logins(clients) == [(1, 0), (1, 0)]
    assert answered is not None and [len(client.snapshot_requests) for client in clients] == [0, 1]


async def test_a_failed_login_is_logged_by_its_type_alone_and_tried_again_no_sooner_than_the_retry_interval(
    clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SinoPac's refusal of a login can quote the login's person id, so the log names the error's type and status alone."""
    logger = RecordingLogger()
    refused = ConnectionError("Sinopac refused the login of A123456789 during maintenance")
    made = list[int]()

    async with site(shioaji_test_config(tmp_path, monkeypatch), logger) as switch:
        clients[0].market_data_error = TokenError(401, "token expired")
        await page_quote(switch)
        LOGIN_REFUSALS.append(refused)

        for seconds in (1, 30, 61, 62):
            clock[0] = MONDAY_10_00 + timedelta(seconds=seconds)
            await page_quote(switch)
            made.append(len(clients))

        LOGIN_REFUSALS.clear()
        clock[0] = MONDAY_10_00 + timedelta(seconds=122)
        answered = await page_quote(switch)

    failures = [message for level, message in logger.records if "login failed" in message]
    assert made == [2, 2, 3, 3], "one login a minute while SinoPac refuses them"
    assert answered is not None and len(clients) == 4
    assert failures and all("ConnectionError" in failure for failure in failures)
    assert not any("A123456789" in message for _, message in logger.records)


async def test_a_new_login_that_fails_leaves_the_stale_login_serving_until_one_succeeds(
    clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tuesday's first request finds Monday's login stale, and SinoPac refuses the new one: the page reads on Monday's."""
    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger()) as switch:
        clock[0] = MONDAY_10_00 + timedelta(days=1)
        clients[0].snapshot_answers = {"2330": snapshot("2330", clock[0] - timedelta(minutes=1), 102.0, 10)}
        LOGIN_REFUSALS.append(ConnectionError("Sinopac is under maintenance"))
        answered = await page_quote(switch)

    assert answered is not None and answered.close == 102.0
    assert [len(client.logins) for client in clients] == [1, 1] and [len(client.snapshot_requests) for client in clients] == [1, 0]


async def test_a_new_login_that_succeeds_after_its_runtime_stopped_waiting_is_taken_up_by_the_next_request_with_sinopac_up(
    clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Tuesday's new login outlasts api.settings_build_timeout_seconds, so the page reads on Monday's, and succeeds after:
    the current runtime's SinoPac then keeps a client that is no longer the connection's and reports down. The next
    request opens a runtime on that login, making none, and SinoPac is up on it.
    """
    config = shioaji_test_config(tmp_path, monkeypatch)
    config.api.settings_build_timeout_seconds = 1
    slow = threading.Event()

    async with site(config, RecordingLogger()) as switch:
        clock[0] = MONDAY_10_00 + timedelta(days=1)
        clients[0].snapshot_answers = {"2330": snapshot("2330", clock[0] - timedelta(minutes=1), 102.0, 10)}
        LOGIN_GATES.append(slow)
        stale = await page_quote(switch)
        LOGIN_GATES.clear()

        with switch.hold() as before:
            connection, broker = before.runtime.shioaji, before.runtime.real_broker
            assert connection is not None and connection.login is not None and broker is not None
            slow.set()
            await asyncio.shield(connection.login)
            left_down = not broker.link().up

        answered = await page_quote(switch)

        with switch.hold() as after:
            link = after.runtime.real_broker.link() if after.runtime.real_broker is not None else None

    assert stale is not None and left_down
    assert answered is not None and link is not None and link.up
    assert logins(clients) == [(1, 0), (1, 0)], "the login left running is taken up and none is made again"
    assert [len(client.snapshot_requests) for client in clients] == [1, 1]


async def test_a_new_login_never_switches_sinopacs_server_whatever_the_files_on_disk_name(
    clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The files name production with ordering off, a switch no reload made yet: the new login is on the simulation server still."""
    project = switch_project(tmp_path)
    edit(project, "server: simulation", "server: production")
    clock[0] = FRIDAY_10_00

    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger(), project) as switch:
        clock[0] = MONDAY_10_00
        await page_quote(switch)

        with switch.hold() as current:
            server = current.runtime.config.shioaji.server

    assert len(clients) == 2 and [client.simulation for client in clients] == [True, True]
    assert server == ShioajiServer.SIMULATION


def sinopac_runtime(harness: CliHarness, connection: ShioajiConnection) -> Runtime:
    """The harness's site whose SinoPac is the real adapter on the client of `connection`'s latest login, as a runtime opens it."""
    login = harness.config.shioaji.login()
    assert login is not None
    broker = ShioajiExecutionProvider(connection, login, harness.config, harness.clock, harness.logger)
    dependencies = replace(harness.dependencies, real_broker=broker, shioaji=connection)
    return runtime_for(replace(harness, dependencies=dependencies), harness.config)


def logged_in_on(
    harness: CliHarness, first: FakeShioaji, *, record_shared: bool = True
) -> tuple[ShioajiConnection, ShioajiQuoteProvider, list[FakeShioaji]]:
    """
    A connection whose first login is on `first`; each later one is on a new client of the same account, which lists
    the orders the clients before it sent, unless `record_shared` is False.
    """
    login = harness.config.shioaji.login()
    assert login is not None
    connection, made = ShioajiConnection(client=first), [first]

    def new_client() -> FakeShioaji:
        made.append(same_account(made[-1]) if record_shared else FakeShioaji())
        return made[-1]

    quotes = ShioajiQuoteProvider(
        connection, new_client, login, harness.config.shioaji, harness.clock, harness.config.market_data, 1000, SilentLogger()
    )
    return connection, quotes, made


def sinopac_harness() -> CliHarness:
    harness = build_harness(config=sinopac_setup(harness_config(), ShioajiServer.SIMULATION), sinopac=True)
    harness.prices.realtime["2330"] = bar(harness.clock.now() - timedelta(minutes=1), 100.0)
    return harness


async def test_a_run_keeps_the_client_it_started_on_while_the_login_is_made_again_and_the_next_run_orders_on_the_new_one() -> None:
    """
    Shioaji reports the session down while the run's order is at SinoPac, and a new login is made. The new client here
    lists nothing the one before sent, so the order would be left unconfirmed were its status read there.
    """
    harness, first = sinopac_harness(), FakeShioaji(place_gate=threading.Event())
    connection, quotes, clients = logged_in_on(harness, first, record_shared=False)
    await quotes.connect()
    before = sinopac_runtime(harness, connection)
    run = asyncio.create_task(before.pipeline_for(ADMINISTRATOR, ExecutionProvider.SHIOAJI).buy_manually(analysed_stock(), 1000))

    async with asyncio.timeout(5):
        while not first.placed:
            await asyncio.sleep(0.01)

    first.session_down()
    await quotes.connect()
    after = sinopac_runtime(harness, connection)
    first.place_gate.set()
    [kept] = (await run).orders
    [renewed] = (await after.pipeline_for(ADMINISTRATOR, ExecutionProvider.SHIOAJI).buy_manually(analysed_stock(), 1000)).orders

    assert (kept.status, kept.filled_quantity, renewed.status, renewed.filled_quantity) == (
        OrderStatus.FILLED,
        1000,
        OrderStatus.FILLED,
        1000,
    )
    assert [(len(client.logins), len(client.placed)) for client in clients] == [(1, 1), (1, 1)]
    assert before.real_broker is not None and after.real_broker is not None
    assert (before.real_broker.link().up, after.real_broker.link().up) == (False, True), "nothing new orders on the client before"


async def test_after_a_new_login_the_timer_settles_on_it_what_the_login_before_sent_and_the_runtime_before_leaves_it() -> None:
    """The same as after a restart: update_status(account) on the new login lists the day's orders of the account."""
    harness, first = sinopac_harness(), FakeShioaji()
    connection, quotes, clients = logged_in_on(harness, first)
    await quotes.connect()
    before = sinopac_runtime(harness, connection)
    lost = unconfirmed_buy(harness)
    listed_at_sinopac(first, lost, Report(Status.Filled, ((100.0, 1),)))
    first.session_down()
    await quotes.connect()
    after = sinopac_runtime(harness, connection)

    await settle_users_orders(before)
    left = harness.journal.orders[lost.id].status if isinstance(harness.journal, FakeTradingJournal) else None
    await settle_users_orders(after)

    assert isinstance(harness.journal, FakeTradingJournal)
    settled = harness.journal.orders[lost.id]
    assert (left, settled.status, settled.filled_quantity) == (OrderStatus.UNCONFIRMED, OrderStatus.FILLED, 1000)
    assert clients[1].account_refreshes and not first.account_refreshes, "the login before is asked nothing after the new one"
