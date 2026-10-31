"""UtcDateTime against a real SQLite file: the one place a datetime crosses into or out of the database."""

import importlib
import pkgutil
import sqlite3
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import DateTime
from sqlalchemy.exc import StatementError
from sqlmodel import SQLModel
from support.settings import shipped_config
from trading_stack import MONDAY_10_00, MovableClock, SilentLogger

import c_infrastructure.database.models
from a_domain.model.trading.watchlist_entry import WatchlistEntry
from a_domain.types.enums import WatchlistType
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.database.utc_datetime import UtcDateTime

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncIterator[DatabaseConnector]:
    connector = DatabaseConnector(config=shipped_config(tmp_path), logger=SilentLogger())
    await connector.init_db()
    yield connector
    await connector.close()


def stored_watchlist(tmp_path: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(tmp_path / "stock_agent.db") as connection:
        return connection.execute("SELECT created_at, expires_at FROM watchlists").fetchall()


async def test_a_taiwan_time_is_stored_as_utc_and_reads_back_as_the_same_aware_instant(db: DatabaseConnector, tmp_path: Path) -> None:
    repository = WatchlistRepository(db=db, logger=SilentLogger(), market_clock=MovableClock(MONDAY_10_00))
    entry = WatchlistEntry(
        stock_id="2330", watchlist_type=WatchlistType.TECHNICAL, created_at=MONDAY_10_00, expires_at=MONDAY_10_00 + timedelta(hours=8)
    )

    await repository.save([entry])
    [loaded] = await repository.get_active()

    assert (loaded.created_at, loaded.expires_at) == (entry.created_at, entry.expires_at)
    assert (loaded.created_at.utcoffset(), loaded.expires_at and loaded.expires_at.utcoffset()) == (timedelta(0), timedelta(0))
    assert stored_watchlist(tmp_path) == [("2026-10-19 02:00:00.000000", "2026-10-19 10:00:00.000000")]


async def test_a_naive_time_is_refused_and_nothing_is_stored(db: DatabaseConnector, tmp_path: Path) -> None:
    repository = WatchlistRepository(db=db, logger=SilentLogger(), market_clock=MovableClock(MONDAY_10_00))
    naive = WatchlistEntry(
        stock_id="2330", watchlist_type=WatchlistType.MANUAL, created_at=datetime(2026, 10, 19, 10, 0), expires_at=None
    )

    with pytest.raises(StatementError) as refused:
        await repository.save([naive])

    assert isinstance(refused.value.orig, ValueError)
    assert stored_watchlist(tmp_path) == []


def test_every_datetime_column_of_every_table_is_a_utc_datetime() -> None:
    for module in pkgutil.iter_modules(c_infrastructure.database.models.__path__):
        importlib.import_module(f"{c_infrastructure.database.models.__name__}.{module.name}")

    columns = [(table.name, column.name, column.type) for table in SQLModel.metadata.tables.values() for column in table.columns]

    assert ("ohlcv_data", "ts") in [(table, name) for table, name, column_type in columns if isinstance(column_type, UtcDateTime)]
    assert [(table, name) for table, name, column_type in columns if isinstance(column_type, DateTime)] == []
