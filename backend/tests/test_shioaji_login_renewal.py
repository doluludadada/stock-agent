"""
The site's Shioaji login made again on a new client by the timer's look (RuntimeSwitch.log_in_again), never by a
request: after Shioaji refused its token, from the market day's shioaji.login_renewal_time on, and after a login failed
no sooner than a wait that starts at shioaji.login_retry_seconds and doubles up to shioaji.login_retry_max_seconds. A
new login becomes the site's only with everything the login before gave it. It takes effect for the next run and read:
a run under way keeps ordering on the client it started on, and SinoPac's record of the day settles on the new one
what the earlier one sent. A reload opens on the login that is up, stale or not.
"""

import asyncio
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
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
from a_domain.types.errors import BrokerNotAnswering
from b_application.config.app_config import AppConfig
from c_infrastructure.market.shioaji_quote_provider import ShioajiConnection, ShioajiQuoteProvider
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock
from c_infrastructure.trading.shioaji import execution_provider
from c_infrastructure.trading.shioaji.execution_provider import ShioajiExecutionProvider
from d_presentation.dependencies import ProcessState, Runtime, get_project_root, open_runtime
from d_presentation.live_runtime import RuntimeSwitch, SettingsReloaded
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

NO_STOCK_ACCOUNT: list[bool] = []
"""While the test holds True here, the next client's login succeeds and returns no stock account."""


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch, clock: list[datetime]) -> list[FakeShioaji]:
    """Every Shioaji client a runtime makes, each answering 2330's last trade a minute before it was made."""
    made: list[FakeShioaji] = []
    LOGIN_REFUSALS.clear()
    LOGIN_GATES.clear()
    NO_STOCK_ACCOUNT.clear()

    def client(simulation: bool) -> FakeShioaji:
        traded = snapshot("2330", clock[0] - timedelta(minutes=1), 101.0, 10)
        contracts, refusal = FakeContracts(FakeStocks({"2330": stock("2330")})), LOGIN_REFUSALS[0] if LOGIN_REFUSALS else None
        gate, account = LOGIN_GATES[0] if LOGIN_GATES else None, {"account_at_login": None} if NO_STOCK_ACCOUNT else {}
        made.append(
            FakeShioaji(
                simulation, Contracts=contracts, snapshot_answers={"2330": traded}, login_error=refusal, login_gate=gate, **account
            )
        )
        return made[-1]

    monkeypatch.setattr(shioaji, "Shioaji", client)
    return made


@asynccontextmanager
async def site(config: AppConfig, logger: RecordingLogger, project: Path | None = None) -> AsyncIterator[RuntimeSwitch]:
    """The process's runtimes, the first opened on `config`, each later one as the switch opens it."""
    shared = ProcessState(logger=logger, attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())
    switch = RuntimeSwitch(
        lambda candidate, replaced: open_runtime(candidate, shared, replaced=replaced), project or get_project_root(), logger
    )
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


async def test_a_refused_token_answers_no_quote_and_no_request_logs_in_again_but_the_timers_next_look_does_on_a_new_client(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Shioaji answered TokenError at 09:05 on 2026-11-20 to a login 26 hours old, and the site kept asking it. A request
    never waits for SinoPac, so the timer's look makes the login again.
    """
    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger()) as switch:
        clients[0].market_data_error = TokenError(401, "token expired")
        refused, still_refused = await page_quote(switch), await page_quote(switch)
        made_by_requests = len(clients)
        renewed = await switch.log_in_again()
        answered = await page_quote(switch)

    assert (refused, still_refused, made_by_requests, renewed) == (None, None, 1, True)
    assert answered is not None and answered.close == 101.0
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
async def test_a_login_made_on_a_market_day_is_made_again_at_the_timers_first_look_from_the_next_market_days_renewal_time(
    asked_at: datetime,
    logged_in_again: bool,
    clients: list[FakeShioaji],
    clock: list[datetime],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Friday's login serves through the weekend. Monday's first look of the timer from 08:15 logs in again, and the
    session's quote is the new login's.
    """
    clock[0] = FRIDAY_10_00

    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger()) as switch:
        clock[0] = asked_at
        await switch.log_in_again()
        made_at_the_look = len(clients)
        clock[0] = MONDAY_10_00
        await switch.log_in_again()
        answered = await page_quote(switch)

    assert made_at_the_look == (2 if logged_in_again else 1)
    assert len(clients) == 2 and logins(clients) == [(1, 0), (1, 0)]
    assert answered is not None and [len(client.snapshot_requests) for client in clients] == [0, 1]


async def test_a_failed_login_is_logged_by_its_type_alone_and_tried_again_after_a_wait_that_doubles(
    clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    SinoPac's refusal of a login can quote the login's person id, so the log names the error's type and status alone.
    The second login comes shioaji.login_retry_seconds after the first refusal, the third twice that after the second.
    """
    logger = RecordingLogger()
    refused = ConnectionError("Sinopac refused the login of A123456789 during maintenance")
    made = list[int]()

    async with site(shioaji_test_config(tmp_path, monkeypatch), logger) as switch:
        clients[0].market_data_error = TokenError(401, "token expired")
        await page_quote(switch)
        LOGIN_REFUSALS.append(refused)

        for seconds in (1, 30, 61, 62, 122, 181):
            clock[0] = MONDAY_10_00 + timedelta(seconds=seconds)
            await switch.log_in_again()
            made.append(len(clients))

        LOGIN_REFUSALS.clear()
        clock[0] = MONDAY_10_00 + timedelta(seconds=421)
        await switch.log_in_again()
        answered = await page_quote(switch)

    failures = [message for level, message in logger.records if "login failed" in message]
    assert made == [2, 2, 3, 3, 3, 4], "a minute after the first refusal, then two minutes after the second"
    assert answered is not None and len(clients) == 5
    assert failures and all("ConnectionError" in failure for failure in failures)
    assert not any("A123456789" in message for _, message in logger.records)


async def test_a_new_login_that_fails_leaves_the_stale_login_serving_until_one_succeeds(
    clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tuesday's first look finds Monday's login stale, and SinoPac refuses the new one: the page reads on Monday's."""
    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger()) as switch:
        clock[0] = MONDAY_10_00 + timedelta(days=1)
        clients[0].snapshot_answers = {"2330": snapshot("2330", clock[0] - timedelta(minutes=1), 102.0, 10)}
        LOGIN_REFUSALS.append(ConnectionError("Sinopac is under maintenance"))
        await switch.log_in_again()
        answered = await page_quote(switch)

    assert answered is not None and answered.close == 102.0
    assert [len(client.logins) for client in clients] == [1, 1] and [len(client.snapshot_requests) for client in clients] == [1, 0]


async def test_a_new_login_that_succeeds_after_the_timers_look_stopped_waiting_is_taken_up_at_the_next_look_with_sinopac_up_throughout(
    clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Tuesday's new login outlasts api.settings_build_timeout_seconds, so the look gives up on it and the page reads on
    Monday's, and it succeeds after. Monday's SinoPac stays up all along, since its own login was never reported down,
    and the next look opens a runtime on the new login, making none.
    """
    config = shioaji_test_config(tmp_path, monkeypatch)
    config.api.settings_build_timeout_seconds = 1
    slow = threading.Event()

    async with site(config, RecordingLogger()) as switch:
        clock[0] = MONDAY_10_00 + timedelta(days=1)
        clients[0].snapshot_answers = {"2330": snapshot("2330", clock[0] - timedelta(minutes=1), 102.0, 10)}
        LOGIN_GATES.append(slow)
        renewed_in_time = await switch.log_in_again()
        LOGIN_GATES.clear()
        stale = await page_quote(switch)

        with switch.hold() as before:
            connection, broker = before.runtime.shioaji, before.runtime.real_broker
            assert connection is not None and connection.login is not None and broker is not None
            up_while_pending = broker.link().up
            slow.set()
            await asyncio.shield(connection.login)
            up_after = broker.link().up

        taken_up = await switch.log_in_again()
        answered = await page_quote(switch)

        with switch.hold() as after:
            link = after.runtime.real_broker.link() if after.runtime.real_broker is not None else None

    assert (renewed_in_time, up_while_pending, up_after, taken_up) == (False, True, True, True)
    assert stale is not None and stale.close == 102.0
    assert answered is not None and link is not None and link.up
    assert logins(clients) == [(1, 0), (1, 0)], "the login left running is taken up and none is made again"
    assert [len(client.snapshot_requests) for client in clients] == [1, 1]


async def test_a_renewal_whose_new_login_has_no_stock_account_leaves_the_runtime_before_current_until_a_login_brings_one(
    clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Tuesday's renewal logs in on a client that returns no stock account. That login counts as failed: the runtime of
    Monday's login stays current with its quotes and its SinoPac up, and the renewal is made again after
    shioaji.login_retry_seconds, on a new client that brings the account.
    """
    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger()) as switch:
        clock[0] = MONDAY_10_00 + timedelta(days=1)
        clients[0].snapshot_answers = {"2330": snapshot("2330", clock[0] - timedelta(minutes=1), 102.0, 10)}
        NO_STOCK_ACCOUNT.append(True)
        without_account = await switch.log_in_again()
        answered = await page_quote(switch)

        with switch.hold() as kept:
            kept_link = kept.runtime.real_broker.link() if kept.runtime.real_broker is not None else None

        NO_STOCK_ACCOUNT.clear()
        clock[0] += timedelta(seconds=61)
        renewed = await switch.log_in_again()

        with switch.hold() as current:
            link = current.runtime.real_broker.link() if current.runtime.real_broker is not None else None

    assert (without_account, renewed) == (False, True)
    assert answered is not None and answered.close == 102.0, "the page reads on Monday's login"
    assert kept_link is not None and kept_link.up and link is not None and link.up
    assert len(clients) == 3


async def test_after_a_refused_token_a_new_login_without_a_stock_account_becomes_the_sites_for_its_quotes_without_sinopac(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Once Shioaji refused the token of the client SinoPac ordered on, the site has no SinoPac left to keep, so a new login
    that returns no stock account counts as made: the pages read on it and the site offers no SinoPac.
    """
    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger()) as switch:
        clients[0].market_data_error = TokenError(401, "token expired")
        await page_quote(switch)
        NO_STOCK_ACCOUNT.append(True)
        renewed = await switch.log_in_again()
        answered = await page_quote(switch)

        with switch.hold() as current:
            broker = current.runtime.real_broker

    assert (renewed, broker) == (True, None)
    assert answered is not None and len(clients) == 2


async def test_a_renewal_without_sinopac_becomes_the_sites_once_the_sinopac_before_it_went_down_while_the_new_login_is_up(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Shioaji refused the token of the client SinoPac ordered on. The timer's new login comes up, but SinoPac's check of
    it fails, as the CA certificate's activation on production can: the site has no SinoPac left to keep, so it takes
    the new login's quotes.
    """

    async def refused(broker: ShioajiExecutionProvider) -> None:
        raise RuntimeError("the CA certificate was not activated")

    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger()) as switch:
        clients[0].market_data_error = TokenError(401, "token expired")
        await page_quote(switch)
        monkeypatch.setattr(ShioajiExecutionProvider, "connect", refused)
        renewed = await switch.log_in_again()
        answered = await page_quote(switch)

        with switch.hold() as current:
            broker = current.runtime.real_broker

    assert (renewed, broker) == (True, None)
    assert answered is not None and len(clients) == 2


@asynccontextmanager
async def reloading_site(config: AppConfig, project: Path) -> AsyncIterator[RuntimeSwitch]:
    """A site on `config` whose files on disk, `project`, differ from it, so a reload opens a runtime, on `config` still."""
    shared = ProcessState(logger=RecordingLogger(), attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())
    switch = RuntimeSwitch(lambda _, replaced: open_runtime(config, shared, replaced=replaced), project, shared.logger)
    await switch.start(config)

    try:
        yield switch
    finally:
        await switch.close()


async def test_a_reload_after_a_refused_token_opens_at_once_without_quotes_and_the_timers_next_look_logs_in(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Shioaji refused the token of the site's login, and an edit on disk comes while SinoPac would answer a new login
    later than api.settings_build_timeout_seconds: the reload opens at once without quotes and makes no login, so it is
    not refused, and the timer's next look logs in.
    """
    config, slow = shioaji_test_config(tmp_path, monkeypatch), threading.Event()
    config.api.settings_build_timeout_seconds = 4

    async with reloading_site(config, switch_project(tmp_path)) as switch:
        clients[0].market_data_error = TokenError(401, "token expired")
        await page_quote(switch)
        LOGIN_GATES.append(slow)

        try:
            reloaded = await switch.reload()
        finally:
            slow.set()

        with switch.hold() as current:
            quotes, made_by_the_reload = current.runtime.realtime_quotes, len(clients)

        LOGIN_GATES.clear()
        renewed = await switch.log_in_again()
        answered = await page_quote(switch)

    assert isinstance(reloaded, SettingsReloaded) and switch.refused is None
    assert (quotes, made_by_the_reload, renewed) == (False, 1, True)
    assert answered is not None and len(clients) == 2


async def test_a_runtime_whose_sinopac_kept_the_client_before_a_login_that_came_up_while_it_opened_is_replaced_at_the_next_look(
    clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Tuesday's renewal outlasts the look's wait and comes up while an edit on disk opens a runtime on Monday's login,
    after that runtime's SinoPac took Monday's client. The runtime is due at once, and once Shioaji refuses Monday's
    token the next look takes the new login up, so the site keeps SinoPac.
    """
    config, slow = shioaji_test_config(tmp_path, monkeypatch), threading.Event()
    config.api.settings_build_timeout_seconds = 4
    checked = ShioajiExecutionProvider.connect

    async def checked_while_the_renewal_comes_up(broker: ShioajiExecutionProvider) -> None:
        connection = switch.opened[-1].runtime.shioaji
        assert connection is not None and connection.login is not None
        slow.set()
        await asyncio.shield(connection.login)
        await checked(broker)

    async with reloading_site(config, switch_project(tmp_path)) as switch:
        clock[0] = MONDAY_10_00 + timedelta(days=1)
        LOGIN_GATES.append(slow)
        renewed_in_time = await switch.log_in_again()
        LOGIN_GATES.clear()

        with monkeypatch.context() as patched:
            patched.setattr(ShioajiExecutionProvider, "connect", checked_while_the_renewal_comes_up)
            reloaded = await switch.reload()

        with switch.hold() as opened:
            kept, due = opened.runtime.real_broker, opened.runtime.login_due

        assert kept is not None
        clients[0].refusals["list_positions"] = TokenError(401, "token expired")

        with pytest.raises(BrokerNotAnswering):
            await kept.get_account()

        renewed = await switch.log_in_again()

        with switch.hold() as current:
            link = current.runtime.real_broker.link() if current.runtime.real_broker is not None else None

    assert isinstance(reloaded, SettingsReloaded)
    assert (renewed_in_time, due, renewed) == (False, True, True)
    assert link is not None and link.up
    assert len(clients) == 2, "the login that came up is taken up and none is made again"


@pytest.mark.parametrize("new_login", ["refused", "slow"])
async def test_a_reload_while_the_login_is_stale_opens_on_it_with_quotes_and_sinopac_and_makes_no_login(
    new_login: str, clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    An edit on disk on Monday at 08:20, while Friday's login still serves and SinoPac would refuse a new one or not
    answer it: the reload opens on Friday's login at once, and the renewal stays the timer's.
    """
    config, project, slow = shioaji_test_config(tmp_path, monkeypatch), switch_project(tmp_path), threading.Event()
    config.api.settings_build_timeout_seconds = 1
    clock[0] = FRIDAY_10_00
    shared = ProcessState(logger=RecordingLogger(), attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())
    switch = RuntimeSwitch(lambda _, replaced: open_runtime(config, shared, replaced=replaced), project, shared.logger)
    await switch.start(config)

    try:
        clock[0] = MONDAY_10_00.replace(hour=8, minute=20)
        (LOGIN_REFUSALS if new_login == "refused" else LOGIN_GATES).append(
            ConnectionError("Sinopac is under maintenance") if new_login == "refused" else slow
        )
        reloaded = await switch.reload()

        with switch.hold() as current:
            quotes, broker = current.runtime.realtime_quotes, current.runtime.real_broker
            link = broker.link() if broker is not None else None
    finally:
        slow.set()
        await switch.close()

    assert isinstance(reloaded, SettingsReloaded)
    assert quotes and link is not None and link.up
    assert len(clients) == 1, "the reload made no login"


async def test_a_page_answers_at_once_on_the_login_before_while_the_timers_look_waits_for_a_new_one(
    clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SinoPac slow to answer Tuesday's renewal keeps no request waiting: the look waits, and the page reads on Monday's."""
    slow = threading.Event()

    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger()) as switch:
        clock[0] = MONDAY_10_00 + timedelta(days=1)
        clients[0].snapshot_answers = {"2330": snapshot("2330", clock[0] - timedelta(minutes=1), 102.0, 10)}
        LOGIN_GATES.append(slow)
        renewal = asyncio.get_running_loop().create_task(switch.log_in_again())

        try:
            async with asyncio.timeout(5):
                while len(clients) < 2 or not clients[1].logins:
                    await asyncio.sleep(0.01)

            async with asyncio.timeout(0.5):
                answered = await page_quote(switch)
        finally:
            slow.set()

        renewed = await renewal

    assert answered is not None and answered.close == 102.0
    assert renewed and [len(client.snapshot_requests) for client in clients] == [1, 0]


async def test_a_sinopac_that_refuses_every_login_for_a_day_is_asked_after_waits_that_double_up_to_their_ceiling(
    clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    From Tuesday 08:15 SinoPac refuses every login and the timer looks once a minute for a day. It is asked at the first
    look, then after 1, 2, 4 and 8 minutes, then every 15 (shioaji.login_retry_max_seconds), on one new client each
    time: 100 clients in the day, where a login a minute made 1,441.
    """
    expected = [0, 1, 3, 7, *range(15, 24 * 60, 15)]
    asked: list[int] = []

    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger()) as switch:
        LOGIN_REFUSALS.append(ConnectionError("Sinopac is under maintenance"))
        renewal_time = MONDAY_10_00.replace(hour=8, minute=15) + timedelta(days=1)

        for minute in range(24 * 60):
            clock[0], made = renewal_time + timedelta(minutes=minute), len(clients)
            await switch.log_in_again()
            asked += [minute] if len(clients) > made else []
            assert asked == expected[: len(asked)], f"asked at minute {minute}"

    assert asked == expected and len(clients) == 100


async def test_a_new_login_never_switches_sinopacs_server_whatever_the_files_on_disk_name(
    clients: list[FakeShioaji], clock: list[datetime], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The files name production with ordering off, a switch no reload made yet: the new login is on the simulation server still."""
    project = switch_project(tmp_path)
    edit(project, "server: simulation", "server: production")
    clock[0] = FRIDAY_10_00

    async with site(shioaji_test_config(tmp_path, monkeypatch), RecordingLogger(), project) as switch:
        clock[0] = MONDAY_10_00
        await switch.log_in_again()

        with switch.hold() as current:
            server = current.runtime.config.shioaji.server

    assert len(clients) == 2 and [client.simulation for client in clients] == [True, True]
    assert server == ShioajiServer.SIMULATION


def sinopac_runtime(harness: CliHarness, connection: ShioajiConnection) -> Runtime:
    """The harness's site whose SinoPac is the real adapter on the client of `connection`'s latest login, as a runtime opens it."""
    login = harness.config.shioaji.login()
    assert login is not None
    broker = ShioajiExecutionProvider(connection, connection.client, login, harness.config, harness.clock, harness.logger)
    dependencies = replace(harness.dependencies, real_broker=broker, shioaji=connection, shioaji_client=connection.client)
    return runtime_for(replace(harness, dependencies=dependencies), harness.config)


def logged_in_on(
    harness: CliHarness, first: FakeShioaji, *, record_shared: bool = True
) -> tuple[ShioajiConnection, Callable[[FakeShioaji | None], Awaitable[None]], list[FakeShioaji]]:
    """
    A connection whose first login is on `first`, and what a runtime that opens on it does with the login: connect past
    the client a renewal replaces, or, given None, on any login that is up. Each later login is on a new client of the
    same account, which lists the orders the clients before it sent, unless `record_shared` is False.
    """
    login = harness.config.shioaji.login()
    assert login is not None
    connection, made = ShioajiConnection(client=first), [first]

    def new_client() -> FakeShioaji:
        made.append(same_account(made[-1]) if record_shared else FakeShioaji())
        return made[-1]

    async def connect(replaced: FakeShioaji | None) -> None:
        shioaji, market_data = harness.config.shioaji, harness.config.market_data
        await ShioajiQuoteProvider(
            connection, new_client, login, shioaji, harness.clock, market_data, 1000, SilentLogger(), True, replaced
        ).connect()

    return connection, connect, made


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
    connection, connect, clients = logged_in_on(harness, first, record_shared=False)
    await connect(None)
    before = sinopac_runtime(harness, connection)
    run = asyncio.create_task(before.pipeline_for(ADMINISTRATOR, ExecutionProvider.SHIOAJI).buy_manually(analysed_stock(), 1000))

    async with asyncio.timeout(5):
        while not first.placed:
            await asyncio.sleep(0.01)

    first.session_down()
    await connect(first)
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
    connection, connect, clients = logged_in_on(harness, first)
    await connect(None)
    before = sinopac_runtime(harness, connection)
    lost = unconfirmed_buy(harness)
    listed_at_sinopac(first, lost, Report(Status.Filled, ((100.0, 1),)))
    first.session_down()
    await connect(first)
    after = sinopac_runtime(harness, connection)

    await settle_users_orders(before)
    left = harness.journal.orders[lost.id].status if isinstance(harness.journal, FakeTradingJournal) else None
    await settle_users_orders(after)

    assert isinstance(harness.journal, FakeTradingJournal)
    settled = harness.journal.orders[lost.id]
    assert (left, settled.status, settled.filled_quantity) == (OrderStatus.UNCONFIRMED, OrderStatus.FILLED, 1000)
    assert clients[1].account_refreshes and not first.account_refreshes, "the login before is asked nothing after the new one"


async def test_a_run_on_the_login_before_a_renewal_keeps_ordering_on_its_client_until_shioaji_refuses_that_clients_token() -> None:
    """
    Friday's login is renewed on Monday on a new client while a run holds the runtime of Friday's login and its Pipeline:
    the rest of that run orders on Friday's client, and the next run on the new one. A refused token on Friday's client then takes
    down only the runtime that kept it.
    """
    harness, first = sinopac_harness(), FakeShioaji()
    monday = harness.clock.now()
    harness.clock.current_time = monday - timedelta(days=3)
    connection, connect, clients = logged_in_on(harness, first, record_shared=False)
    await connect(None)
    before = sinopac_runtime(harness, connection)
    harness.clock.current_time = monday
    run = before.pipeline_for(ADMINISTRATOR, ExecutionProvider.SHIOAJI)
    await connect(first)
    after = sinopac_runtime(harness, connection)

    [kept] = (await run.buy_manually(analysed_stock(), 1000)).orders
    [renewed] = (await after.pipeline_for(ADMINISTRATOR, ExecutionProvider.SHIOAJI).buy_manually(analysed_stock(), 1000)).orders
    assert before.real_broker is not None and after.real_broker is not None
    first.refusals["list_positions"] = TokenError(401, "token expired")

    with pytest.raises(BrokerNotAnswering):
        await before.real_broker.get_account()

    assert (kept.status, renewed.status) == (OrderStatus.FILLED, OrderStatus.FILLED)
    assert [(len(client.logins), len(client.placed)) for client in clients] == [(1, 1), (1, 1)]
    assert (before.real_broker.link().up, after.real_broker.link().up, connection.up) == (False, True, True)
