"""
A runtime closes what it opened, once its owner is done with it or a later startup step fails. The Shioaji login is the
process's: the first runtime on a server logs in, and every later one on that server reuses the login, after a switch
away and back too. No runtime logs a login out, the last one to close included, and every client stays referenced.
"""

import asyncio
import gc
import shutil
import weakref
from contextlib import AsyncExitStack
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import shioaji
from pydantic import SecretStr
from support.fake_daily_history import FakeDailyHistory, session_bar
from support.fake_shioaji import FakeShioaji
from support.fakes import RecordingLogger
from support.settings import sinopac_setup
from trading_stack import SilentLogger

from a_domain.model.market.article import Article
from a_domain.model.market.stock import Stock
from a_domain.ports.system.settings_files import SettingsProblem
from a_domain.rules.fundamentals.trailing_eps import QuarterEps
from a_domain.types.enums import InformationSource, MarketType, SentimentLabel, ShioajiServer, SystemEnvironment
from a_domain.types.values import FiscalQuarter
from b_application.config.app_config import AppConfig, DbConfig
from b_application.config.settings_loader import InvalidSettingsError
from b_application.pipeline import Pipeline
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.sentiment_repository import SentimentRepository
from c_infrastructure.database.repositories.user_store import AccountsKeyError, SqlUserStore
from c_infrastructure.market.mops_fundamentals_provider import save_page
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from c_infrastructure.system.market_clock import TaiwanMarketClock
from d_presentation import dependencies
from d_presentation.dependencies import ProcessState, build_provider_dependencies, get_project_root, load_settings, open_runtime
from d_presentation.live_runtime import ReloadRefused, RuntimeSwitch, SettingsReloaded
from d_presentation.web.scheduled_follows import follow_rankings_on_schedule
from d_presentation.web.workflow_runs import WorkflowRuns

pytestmark = pytest.mark.asyncio

KEY = SecretStr("A" * 43)


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> list[FakeShioaji]:
    """Every Shioaji client a runtime makes; none logs in anywhere."""
    made: list[FakeShioaji] = []
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: made.append(FakeShioaji(simulation)) or made[-1])
    return made


def shioaji_test_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, environment: SystemEnvironment = SystemEnvironment.TEST
) -> AppConfig:
    """
    The shipped settings in `environment` with the simulation server's Shioaji key pair, over the session's database: a
    personal site whose login offers SinoPac on the simulation server.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    shipped = load_settings(get_project_root()).model_copy(update={"project_root": tmp_path})
    config = sinopac_setup(shipped, ShioajiServer.SIMULATION, environment)
    config.accounts.key = KEY
    config.db = DbConfig(_env_file=None)
    return config


def process() -> ProcessState:
    return ProcessState(logger=SilentLogger(), attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())


async def test_a_reload_reuses_the_login_and_closing_the_last_runtime_logs_nothing_out(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, shared, project = shioaji_test_config(tmp_path, monkeypatch), process(), switch_project(tmp_path)
    switch = RuntimeSwitch(lambda _: open_runtime(config, shared), project, shared.logger)
    await switch.start(config)

    try:
        reloaded = await switch.reload()
        await drained(switch)
        open_after_the_reload = [(len(client.logins), client.logouts) for client in clients]
    finally:
        await switch.close()

    assert isinstance(reloaded, SettingsReloaded)
    assert open_after_the_reload == [(1, 0)]
    assert [(len(client.logins), client.logouts) for client in clients] == [(1, 0)], "the closed switch logged nothing out"


async def test_a_reload_whose_startup_fails_after_the_login_leaves_it_to_the_runtime_still_current(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def wrong_key(store: SqlUserStore) -> None:
        raise AccountsKeyError("Restore the original secrets/accounts.key")

    config, shared, project = shioaji_test_config(tmp_path, monkeypatch), process(), switch_project(tmp_path)
    switch = RuntimeSwitch(lambda _: open_runtime(config, shared), project, shared.logger)
    await switch.start(config)

    try:
        with monkeypatch.context() as patched:
            patched.setattr(SqlUserStore, "check_key", wrong_key)
            refused = await switch.reload()

        edit(project, "temperature: 0.7", "temperature: 0.2")
        reloaded = await switch.reload()
        await drained(switch)
        logins = [(len(client.logins), client.logouts) for client in clients]
    finally:
        await switch.close()

    assert isinstance(refused, ReloadRefused) and isinstance(reloaded, SettingsReloaded)
    assert logins == [(1, 0)]


async def test_a_broker_whose_check_after_the_login_fails_offers_no_sinopac_and_keeps_the_one_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[FakeShioaji] = []

    def client(simulation: bool) -> FakeShioaji:
        made.append(fake := FakeShioaji(simulation, account_at_login=None))
        return fake

    monkeypatch.setattr(shioaji, "Shioaji", client)
    shared = process()

    async with AsyncExitStack() as runtimes:
        for _ in range(3):
            runtime = await runtimes.enter_async_context(open_runtime(shioaji_test_config(tmp_path, monkeypatch), shared))
            assert (runtime.realtime_quotes, runtime.real_broker) == (True, None)

        assert [(len(fake.logins), fake.logouts) for fake in made] == [(1, 0)]


async def test_two_runtimes_of_one_process_save_the_same_cached_rows_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A retired runtime still finishing a run and the current one, over one database: one shared row is saved once."""
    config = shioaji_test_config(tmp_path, monkeypatch, SystemEnvironment.DEV)
    shared, clock = process(), TaiwanMarketClock(config.market_hours)
    start, end = clock.history_window(30)
    settled = datetime.combine(clock.last_settled_session(), config.market_hours.close, clock.now().tzinfo)
    sessions = [day for day in (settled.date() - timedelta(days=offset) for offset in range(20)) if day.weekday() < 5]
    stocks = [f"23{attempt:02d}" for attempt in range(10)]
    reports = FakeDailyHistory(
        sessions={day: {stock: session_bar(day, 100.0, change=0.0) for stock in stocks} for day in sessions},
        index={market: sorted(sessions) for market in MarketType},
    )
    monkeypatch.setattr(dependencies, "ExchangeDailyReports", lambda **_: reports)
    databases = [DatabaseConnector(config=config, logger=SilentLogger()) for _ in range(2)]
    runtimes = []

    for database in databases:
        await database.init_db()
        runtimes.append(await build_provider_dependencies(config, database, shared, clock, KEY, None, None))

    failures = []

    for attempt in range(10):
        stock = f"23{attempt:02d}"
        page = QuarterEps(quarter=FiscalQuarter(year=2020 + attempt, quarter=1), cumulative_eps={stock: 1.0}, fetched_at=settled)
        post = Article(
            stock_id=stock,
            source=InformationSource.PTT_STOCK,
            title="Opinion",
            content="Opinion",
            url=f"https://www.ptt.cc/bbs/Stock/{stock}.html",
            published_at=settled,
            fetched_at=settled,
        )
        posts = [replace(post, sentiment=SentimentLabel.BULLISH, sentiment_confidence=0.8)]
        saves = [
            save
            for runtime, database in zip(runtimes, databases, strict=True)
            for save in (
                runtime.price_provider.fetch_history([Stock(stock_id=stock)], start, end),
                save_page(MarketType.TWSE, page, shared.cache_writes, database),
                SentimentRepository(database, shared.cache_writes).save_classified(stock, posts),
            )
        ]
        failures += [
            type(result).__name__ for result in await asyncio.gather(*saves, return_exceptions=True) if isinstance(result, Exception)
        ]

    for database in databases:
        await database.close()

    assert failures == []


async def test_a_login_shioaji_reports_down_answers_no_realtime_quote_until_a_runtime_logs_in_again_on_a_new_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every client stays referenced and none is logged out (ProcessState.shioaji_connections)."""
    made: list[weakref.ref[FakeShioaji]] = []

    def client(simulation: bool) -> FakeShioaji:
        fake = FakeShioaji(simulation)
        made.append(weakref.ref(fake))
        return fake

    monkeypatch.setattr(shioaji, "Shioaji", client)
    config, shared = shioaji_test_config(tmp_path, monkeypatch), process()

    async with open_runtime(config, shared) as first:
        at_open = first.realtime_quotes
        dead = made[0]()
        assert dead is not None
        dead.session_down()
        after_down = first.realtime_quotes
        del dead

        async with open_runtime(config, shared) as second:
            gc.collect()
            clients = [fake for ref in made if (fake := ref()) is not None]
            clients[0].session_down()
            assert (at_open, after_down, second.realtime_quotes) == (True, False, True)
            assert [(len(fake.logins), fake.logouts) for fake in clients] == [(1, 0), (1, 0)]


async def test_the_web_apis_timer_logs_in_again_once_shioaji_reported_the_login_down(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The timer of the scheduled follows makes the login again at its next look, before it looks for a follow."""
    monkeypatch.setenv("ACCOUNTS_KEY", KEY.get_secret_value())
    config = shioaji_test_config(tmp_path, monkeypatch, SystemEnvironment.DEV)
    logger = RecordingLogger()
    shared = ProcessState(logger=logger, attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())
    switch = RuntimeSwitch(lambda _: open_runtime(config, shared), get_project_root(), logger)
    await switch.start(config)

    try:
        clients[0].session_down()
        timer = asyncio.get_running_loop().create_task(follow_rankings_on_schedule(switch, WorkflowRuns(logger)))

        async with asyncio.timeout(10):
            while len(switch.opened) < 2:
                await asyncio.sleep(0.01)

        timer.cancel()

        with switch.hold() as current:
            realtime_quotes = current.runtime.realtime_quotes

        logins = [(len(fake.logins), fake.logouts) for fake in clients]
    finally:
        await switch.close()

    assert realtime_quotes, logger.records
    assert logins == [(1, 0), (1, 0)], "the down client is never logged out, nor collected"


def switch_project(tmp_path: Path) -> Path:
    """A copy of config/ in environment test, the owner's server, which may log in to either SinoPac server."""
    project = tmp_path / "project"
    shutil.copytree(get_project_root() / "config", project / "config")
    edit(project, "environment: dev", "environment: test")
    return project


def edit(project: Path, old: str, new: str) -> None:
    appsetting = project / "config" / "appsetting.yaml"
    text = appsetting.read_text(encoding="utf-8")
    assert old in text
    appsetting.write_text(text.replace(old, new, 1), encoding="utf-8")


async def drained(switch: RuntimeSwitch) -> None:
    """Waits until every runtime but the current one has closed."""
    async with asyncio.timeout(30):
        while any(opened.closing is None for opened in switch.opened[:-1]):
            await asyncio.sleep(0)

        await asyncio.gather(*(opened.closing for opened in switch.opened[:-1] if opened.closing is not None))


def on_both_servers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[ShioajiServer, AppConfig]:
    """
    The site on each SinoPac server, both key sets held, also in the environment the settings files are read with, so a
    switch's checks find the new server's credentials. The opener opens the one of the server the files name.
    """
    simulation = shioaji_test_config(tmp_path, monkeypatch)
    both = (*ShioajiServer.SIMULATION.credentials, *ShioajiServer.PRODUCTION.credentials)
    monkeypatch.chdir(tmp_path)

    for credential in both:
        monkeypatch.setenv(credential.value, credential.value)

    return {
        ShioajiServer.SIMULATION: sinopac_setup(simulation, ShioajiServer.SIMULATION, credentials=both),
        ShioajiServer.PRODUCTION: sinopac_setup(simulation, ShioajiServer.PRODUCTION, credentials=both),
    }


async def test_a_switch_of_the_server_logs_in_there_once_and_a_switch_back_reuses_the_first_login(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configs, shared, project = on_both_servers(tmp_path, monkeypatch), process(), switch_project(tmp_path)
    switch = RuntimeSwitch(lambda candidate: open_runtime(configs[candidate.shioaji.server], shared), project, shared.logger)
    await switch.start(configs[ShioajiServer.SIMULATION])

    try:
        with switch.hold():
            edit(project, "  server: simulation", "  server: production")
            there = await switch.reload()

            with switch.hold() as new:
                switched = (new.runtime.realtime_quotes, new.runtime.real_broker is not None, new.runtime.shioaji.client.simulation)

        await drained(switch)
        after_the_switch = [(client.simulation, len(client.logins), client.logouts) for client in clients]
        edit(project, "  server: production", "  server: simulation")
        back = await switch.reload()
        await drained(switch)

        with switch.hold() as current:
            back_on = (current.runtime.realtime_quotes, current.runtime.real_broker is not None, current.runtime.shioaji.client)
    finally:
        await switch.close()

    assert isinstance(there, SettingsReloaded) and isinstance(back, SettingsReloaded)
    assert switched == (True, True, False), "the new runtime's quotes and SinoPac are on production"
    assert after_the_switch == [(True, 1, 0), (False, 1, 0)], "the simulation login stays open after the switch"
    assert back_on == (True, True, clients[0]), "back on simulation, the runtime orders and quotes on the first login"
    assert [(client.simulation, len(client.logins), client.logouts) for client in clients] == [(True, 1, 0), (False, 1, 0)]


async def test_a_refused_switch_logs_nothing_out_and_a_later_runtime_on_its_server_reuses_its_login(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def locked_out(pipeline: Pipeline, running: object, saving: object) -> None:
        raise InvalidSettingsError([SettingsProblem(message="no administrator could sign in")])

    configs, shared, project = on_both_servers(tmp_path, monkeypatch), process(), switch_project(tmp_path)
    switch = RuntimeSwitch(lambda candidate: open_runtime(configs[candidate.shioaji.server], shared), project, shared.logger)
    await switch.start(configs[ShioajiServer.SIMULATION])

    try:
        edit(project, "  server: simulation", "  server: production")

        with monkeypatch.context() as patched:
            patched.setattr(Pipeline, "confirm_editor_access", locked_out)
            refused = await switch.reload()

        with switch.hold() as current:
            still = current.runtime.shioaji is not None and current.runtime.shioaji.up

        after_the_refusal = [(client.simulation, len(client.logins), client.logouts) for client in clients]
        edit(project, "temperature: 0.7", "temperature: 0.2")
        later = await switch.reload()
        await drained(switch)

        with switch.hold() as current:
            on = current.runtime.shioaji.client if current.runtime.shioaji is not None else None
    finally:
        await switch.close()

    assert isinstance(refused, ReloadRefused) and isinstance(later, SettingsReloaded)
    assert still, "the running runtime keeps its login"
    assert after_the_refusal == [(True, 1, 0), (False, 1, 0)]
    assert on is clients[1], "the later runtime on production reuses the refused runtime's login"
    assert [(client.simulation, len(client.logins), client.logouts) for client in clients] == [(True, 1, 0), (False, 1, 0)]
