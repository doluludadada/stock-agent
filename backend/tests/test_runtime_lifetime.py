"""
A runtime closes what it opened, once its owner is done with it or a later startup step fails. The Shioaji login is the
process's: the first runtime logs in, every later one reuses the login, and nothing logs out, since shioaji 1.3.1
segfaults at the next garbage collection after a logout.
"""

import asyncio
import gc
import weakref
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import shioaji
from pydantic import SecretStr
from support.fake_daily_history import FakeDailyHistory, session_bar
from support.fake_shioaji import FakeShioaji
from support.fakes import RecordingLogger
from support.settings import environment_setup
from trading_stack import SilentLogger

from a_domain.model.market.article import Article
from a_domain.model.market.stock import Stock
from a_domain.rules.fundamentals.trailing_eps import QuarterEps
from a_domain.types.enums import InformationSource, MarketType, SentimentLabel, SystemEnvironment
from a_domain.types.values import FiscalQuarter
from b_application.config.app_config import AppConfig, DbConfig
from b_application.pipeline import Pipeline
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.sentiment_repository import SentimentRepository
from c_infrastructure.database.repositories.user_store import AccountsKeyError, SqlUserStore
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from c_infrastructure.system.market_clock import TaiwanMarketClock
from d_presentation import dependencies
from d_presentation.dependencies import ProcessState, build_provider_dependencies, get_project_root, load_settings, open_runtime
from d_presentation.live_runtime import RuntimeSwitch, collect_daily_data

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
    The shipped settings with the environment's Shioaji key pair, over a SQLite file and a Chroma folder in tmp_path: a
    personal site whose login offers SinoPac on the simulation server.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    shipped = load_settings(get_project_root()).model_copy(update={"project_root": tmp_path})
    config = environment_setup(shipped, environment)
    config.accounts.key = KEY
    config.db = DbConfig(_env_file=None, backend=config.db.backend, chroma_persist_path=str(tmp_path / "chroma"))
    return config


def process() -> ProcessState:
    return ProcessState(logger=SilentLogger(), attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())


async def test_the_runtimes_of_one_process_share_one_shioaji_login_and_never_log_out(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = shioaji_test_config(tmp_path, monkeypatch)
    shared = process()

    for _ in ("startup", "reload"):
        async with open_runtime(config, shared):
            pass

    assert [(len(client.logins), client.logouts) for client in clients] == [(1, 0)]


async def test_a_startup_step_that_fails_after_the_login_leaves_it_for_the_next_runtime(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def wrong_key(store: SqlUserStore) -> None:
        raise AccountsKeyError("Restore the original secrets/accounts.key")

    config, shared = shioaji_test_config(tmp_path, monkeypatch), process()

    with monkeypatch.context() as patched:
        patched.setattr(SqlUserStore, "check_key", wrong_key)

        with pytest.raises(AccountsKeyError):
            async with open_runtime(config, shared):
                pass

    async with open_runtime(config, shared):
        pass

    assert [(len(client.logins), client.logouts) for client in clients] == [(1, 0)]


async def test_a_broker_whose_check_after_the_login_fails_offers_no_sinopac_and_keeps_the_one_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[FakeShioaji] = []

    def client(simulation: bool) -> FakeShioaji:
        made.append(fake := FakeShioaji(simulation, account_at_login=None))
        return fake

    monkeypatch.setattr(shioaji, "Shioaji", client)
    shared = process()

    for _ in range(3):
        async with open_runtime(shioaji_test_config(tmp_path, monkeypatch), shared) as runtime:
            assert (runtime.realtime_quotes, runtime.real_broker) == (True, None)

    assert [(len(fake.logins), fake.logouts) for fake in made] == [(1, 0)]


async def test_two_runtimes_of_one_process_save_the_same_cached_rows_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A retired runtime still finishing a run and the current one, over one database: one shared row is saved once."""
    config = environment_setup(shioaji_test_config(tmp_path, monkeypatch), SystemEnvironment.DEV)
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
                runtime.fundamentals_provider.save_page(MarketType.TWSE, page),
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
    """Every client stays referenced, never logged out: shioaji 1.3.1 segfaults at the next garbage collection after a logout."""
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
    """The timer's runtime loads the shipped settings files, in tmp_path so that no .env of the machine reaches them."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ACCOUNTS_KEY", KEY.get_secret_value())
    config, shared, refreshed = shioaji_test_config(tmp_path, monkeypatch, SystemEnvironment.DEV), process(), asyncio.Event()

    async def archive(pipeline: Pipeline) -> None:
        return None

    async def refresh(pipeline: Pipeline) -> None:
        refreshed.set()

    monkeypatch.setattr(Pipeline, "archive_daily_closes", archive)
    monkeypatch.setattr(Pipeline, "refresh_daily_history", refresh)
    logger = RecordingLogger()
    switch = RuntimeSwitch(lambda _: open_runtime(config, shared), get_project_root(), logger)
    await switch.start(config)

    try:
        clients[0].session_down()
        timer = asyncio.get_running_loop().create_task(collect_daily_data(switch))
        await asyncio.wait_for(refreshed.wait(), 10)
        timer.cancel()

        with switch.hold() as current:
            realtime_quotes = current.runtime.realtime_quotes
    finally:
        await switch.close()

    assert realtime_quotes, logger.records
    assert [(len(fake.logins), fake.logouts) for fake in clients] == [(1, 0), (1, 0)]
