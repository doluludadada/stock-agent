"""
A runtime closes what it opened, once its owner is done with it or a later startup step fails: the broker logs out,
after every login it began, whether that login succeeded, failed, timed out or was cancelled.
"""

import asyncio
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import shioaji
from pydantic import SecretStr
from support.fake_shioaji import FakeShioaji
from support.settings import environment_setup
from trading_stack import SilentLogger

from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.fundamentals.trailing_eps import QuarterEps
from a_domain.types.enums import ExecutionProvider, InformationSource, MarketType, OrderMode, SentimentLabel, SystemEnvironment
from a_domain.types.values import FiscalQuarter
from b_application.config.app_config import AppConfig, DbConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.sentiment_repository import SentimentRepository
from c_infrastructure.database.repositories.user_store import AccountsKeyError, SqlUserStore
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from c_infrastructure.system.market_clock import TaiwanMarketClock
from d_presentation.dependencies import (
    ProcessState,
    TradingSetupError,
    build_provider_dependencies,
    get_project_root,
    load_settings,
    open_runtime,
)

pytestmark = pytest.mark.asyncio

KEY = SecretStr("A" * 43)


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> list[FakeShioaji]:
    """Every Shioaji client a runtime makes; none logs in anywhere."""
    made: list[FakeShioaji] = []
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: made.append(FakeShioaji(simulation)) or made[-1])
    return made


def shioaji_test_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    """The shipped settings on Shioaji in test, over a SQLite file and a Chroma folder in tmp_path."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    shipped = load_settings(get_project_root()).model_copy(update={"project_root": tmp_path})
    config = environment_setup(shipped, SystemEnvironment.TEST, ExecutionProvider.SHIOAJI, OrderMode.DISABLED)
    config.accounts.key = KEY
    config.db = DbConfig(_env_file=None, backend=config.db.backend, chroma_persist_path=str(tmp_path / "chroma"))
    return config


def process() -> ProcessState:
    return ProcessState(logger=SilentLogger(), attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())


async def test_each_runtime_logs_out_of_the_broker_it_logged_in_to_when_it_closes(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = shioaji_test_config(tmp_path, monkeypatch)
    shared = process()

    for opened in (1, 2):
        async with open_runtime(config, shared):
            assert [client.logouts for client in clients] == [1] * (opened - 1) + [0]

    assert [(len(client.logins), client.logouts) for client in clients] == [(1, 1), (1, 1)]


async def test_a_startup_step_that_fails_after_the_login_still_logs_out(
    clients: list[FakeShioaji], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def wrong_key(store: SqlUserStore) -> None:
        raise AccountsKeyError("Restore the original secrets/accounts.key")

    monkeypatch.setattr(SqlUserStore, "check_key", wrong_key)

    with pytest.raises(AccountsKeyError):
        async with open_runtime(shioaji_test_config(tmp_path, monkeypatch), process()):
            pass

    assert [(len(client.logins), client.logouts) for client in clients] == [(1, 1)]


async def test_a_broker_whose_check_after_the_login_fails_logs_out_each_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[FakeShioaji] = []

    def client(simulation: bool) -> FakeShioaji:
        made.append(fake := FakeShioaji(simulation, account_at_login=None))
        return fake

    monkeypatch.setattr(shioaji, "Shioaji", client)

    for _ in range(3):
        with pytest.raises(TradingSetupError, match="the login returned no stock account"):
            async with open_runtime(shioaji_test_config(tmp_path, monkeypatch), process()):
                pass

    assert [(len(fake.logins), fake.logouts) for fake in made] == [(1, 1)] * 3


class SlowLogin(FakeShioaji):
    """A login that waits in its thread until the test lets it end, as a slow broker's does."""

    def __init__(self, simulation: bool) -> None:
        super().__init__(simulation)
        self.started, self.release, self.ended = threading.Event(), threading.Event(), threading.Event()

    def login(self, *args, **kwargs):
        self.started.set()
        self.release.wait(10)

        try:
            return super().login(*args, **kwargs)
        finally:
            self.ended.set()


@pytest.mark.parametrize("stop", ["timeout", "cancel"])
async def test_a_login_cut_short_logs_out_once_its_thread_ends(stop: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[SlowLogin] = []
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: made.append(SlowLogin(simulation)) or made[-1])
    config, deadlines = shioaji_test_config(tmp_path, monkeypatch), []

    async def open_once() -> None:
        async with asyncio.timeout(None) as deadline:
            deadlines.append(deadline)

            async with open_runtime(config, process()):
                pass

    opening = asyncio.create_task(open_once())

    while not made or not made[0].started.is_set():
        await asyncio.sleep(0.01)

    if stop == "timeout":
        deadlines[0].reschedule(asyncio.get_running_loop().time())
    else:
        opening.cancel()

    made[0].release.set()

    with pytest.raises(TimeoutError if stop == "timeout" else asyncio.CancelledError):
        await opening

    await asyncio.to_thread(made[0].ended.wait, 10)
    assert [(len(fake.logins), fake.logouts) for fake in made] == [(1, 1)]


async def test_two_runtimes_of_one_process_save_the_same_cached_rows_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A retired runtime still finishing a run and the current one, over one database: one shared row is saved once."""
    config = environment_setup(
        shioaji_test_config(tmp_path, monkeypatch), SystemEnvironment.DEV, ExecutionProvider.MOCK, OrderMode.MOCK_ONLY
    )
    shared, clock = process(), TaiwanMarketClock(config.market_hours)
    start, end = clock.history_window(30)
    settled = datetime.combine(clock.last_settled_session(), config.market_hours.close, clock.now().tzinfo)

    async def download(provider, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        await asyncio.sleep(0)
        return {
            stock.stock_id: [Ohlcv(ts=settled - timedelta(days=day), close=100.0, volume=1000) for day in range(20)]
            for stock in stocks
        }

    monkeypatch.setattr(YahooFinanceProvider, "fetch_history", download)
    databases = [DatabaseConnector(config=config, logger=SilentLogger()) for _ in range(2)]
    runtimes = []

    for database in databases:
        await database.init_db()
        runtimes.append(await build_provider_dependencies(config, database, shared, clock, KEY, None))

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
