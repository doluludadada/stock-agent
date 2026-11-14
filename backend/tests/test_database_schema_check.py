"""
DatabaseConnector.init_db() against a real PostgreSQL database: it refuses a database of another schema version, or of
none, or of another table layout, and never changes it. tests/test_database_commands.py covers the older version that
`just db-migrate` upgrades.
"""

from pathlib import Path

import pytest
from sqlmodel import SQLModel
from support.databases import database_snapshot, execute, open_database, raw_engine

import c_infrastructure.database.models.mock_trading_dto
import c_infrastructure.database.models.ohlcv_dto
import c_infrastructure.database.models.quarter_eps_dto
import c_infrastructure.database.models.trading_journal_dto
import c_infrastructure.database.models.watchlist_dto  # noqa: F401  (each import registers its tables on SQLModel.metadata)
from c_infrastructure.database.db_connector import OutdatedDatabaseError
from c_infrastructure.database.models.schema_version_dto import SCHEMA_VERSION

pytestmark = pytest.mark.asyncio

# trade_signals as the database held it before the orders table existed.
OLD_TRADE_SIGNALS = """
CREATE TABLE trade_signals (
    stock_id VARCHAR NOT NULL,
    action VARCHAR(4) NOT NULL,
    price_at_signal FLOAT NOT NULL,
    source VARCHAR(9) NOT NULL,
    score INTEGER NOT NULL,
    reason VARCHAR NOT NULL,
    quantity INTEGER NOT NULL,
    stop_loss_price FLOAT,
    generated_at TIMESTAMP NOT NULL,
    id CHAR(32) NOT NULL,
    PRIMARY KEY (id)
)
"""


async def init_db(project_root: Path) -> None:
    connector = open_database(project_root)

    try:
        await connector.init_db()
    finally:
        await connector.close()


async def test_old_trade_signals_layout_stops_startup_and_stays_untouched(tmp_path: Path) -> None:
    await execute(
        OLD_TRADE_SIGNALS,
        "INSERT INTO trade_signals VALUES ('2330', 'BUY', 1000.0, 'TECHNICAL', 80, 'old', 1000, NULL, '2026-10-01', 'a1')",
    )
    before = await database_snapshot()

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    message = str(refused.value)
    assert named_tables(message) == ["trade_signals"]
    assert "decision_id" in message
    assert "Remedy: drop the tables named above. The next start recreates them empty." in message
    assert "ohlcv_data" not in message

    assert before.keys() == {"trade_signals"}
    assert await database_snapshot() == before


# ohlcv_data as the database held it while each bar also stored its session in a trading_date column.
OLD_OHLCV_DATA = """
CREATE TABLE ohlcv_data (
    open FLOAT NOT NULL,
    high FLOAT NOT NULL,
    low FLOAT NOT NULL,
    close FLOAT NOT NULL,
    volume INTEGER NOT NULL,
    adj_close FLOAT,
    stock_id VARCHAR NOT NULL,
    trading_date DATE NOT NULL,
    ts TIMESTAMP NOT NULL,
    PRIMARY KEY (stock_id, ts)
)
"""


async def test_old_ohlcv_cache_layout_stops_startup_and_says_the_cache_refills(tmp_path: Path) -> None:
    await execute(OLD_OHLCV_DATA)

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    message = str(refused.value)
    assert "ohlcv_data (missing columns: change; columns no longer used: adj_close, trading_date)" in message
    assert "Cached prices and EPS refill themselves" in message


async def test_a_database_the_current_models_created_starts_again(tmp_path: Path) -> None:
    await init_db(tmp_path)
    created = await database_snapshot()

    await init_db(tmp_path)

    assert {"trade_signals", "orders", "workflow_runs", "account_snapshots", "mops_quarter_eps"} <= created.keys()
    assert await database_snapshot() == created
    assert await stored_schema_versions() == [SCHEMA_VERSION]


async def stored_schema_versions() -> list[int]:
    return [int(version) for (version,) in (await database_snapshot())["schema_version"][1]]


async def create_current_tables(schema_version: int | None) -> None:
    """Every table with the columns the code declares, as a database another version wrote would hold them."""
    tables = [table for table in SQLModel.metadata.sorted_tables if schema_version is not None or table.name != "schema_version"]
    engine = raw_engine()

    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all, tables=tables)

    await engine.dispose()
    # An older version stored Taiwan wall-clock time here; the current code would read it as UTC.
    await execute(
        "INSERT INTO ohlcv_data (stock_id, ts, open, high, low, close, volume) VALUES ('2330', '2026-10-30 13:30:00', 1, 1, 1, 1, 1)",
        *([] if schema_version is None else [f"INSERT INTO schema_version (version) VALUES ({schema_version})"]),
    )


def named_tables(message: str) -> list[str]:
    return [line.removeprefix("  - ").split(" ")[0] for line in message.splitlines() if line.startswith("  - ")]


async def test_a_database_without_a_schema_version_stops_startup_and_stays_untouched(tmp_path: Path) -> None:
    await create_current_tables(schema_version=None)
    before = await database_snapshot()

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    message = str(refused.value)
    assert {"ohlcv_data", "trade_signals", "watchlists", "mock_cash"} <= set(named_tables(message))
    assert "schema_version" not in named_tables(message)
    assert f"The database's schema version is none, and this version of stock-agent needs {SCHEMA_VERSION}" in message
    assert "Remedy: drop the tables named above. The next start recreates them empty." in message
    assert "Cached prices and EPS refill themselves" in message
    assert "schema_version" not in before
    assert await database_snapshot() == before


@pytest.mark.parametrize("schema_version", [0, SCHEMA_VERSION - 1, SCHEMA_VERSION + 1])
async def test_a_database_with_a_schema_version_no_upgrade_reaches_stops_startup_and_stays_untouched(
    tmp_path: Path, schema_version: int
) -> None:
    await create_current_tables(schema_version=schema_version)
    before = await database_snapshot()

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    message = str(refused.value)
    assert {"ohlcv_data", "trade_signals", "schema_version"} <= set(named_tables(message))
    assert f"schema version is {schema_version}, and this version of stock-agent needs {SCHEMA_VERSION}" in message
    assert "just db-migrate" not in message
    assert await database_snapshot() == before


async def test_dropping_the_named_tables_lets_the_next_start_create_and_stamp_them(tmp_path: Path) -> None:
    await create_current_tables(schema_version=0)

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    await execute(f"DROP TABLE {', '.join(named_tables(str(refused.value)))} CASCADE")
    assert await database_snapshot() == {}

    await init_db(tmp_path)

    assert await stored_schema_versions() == [SCHEMA_VERSION]
    assert (await database_snapshot())["ohlcv_data"][1] == []


async def test_a_current_database_whose_table_changed_names_only_that_table(tmp_path: Path) -> None:
    await init_db(tmp_path)
    await execute("ALTER TABLE ohlcv_data ADD COLUMN trading_date DATE")

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    message = str(refused.value)
    assert named_tables(message) == ["ohlcv_data"]
    assert "columns no longer used: trading_date" in message
    assert "schema version" not in message
