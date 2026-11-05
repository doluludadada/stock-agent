"""
DatabaseConnector.init_db() against real SQLite files: it upgrades a database of an older schema version in place and
keeps every row, and it refuses a database it cannot upgrade, by its table layout or by its schema version, and never
changes it.
"""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlmodel import SQLModel
from support.settings import shipped_config
from trading_stack import SilentLogger

import c_infrastructure.database.models.mock_trading_dto
import c_infrastructure.database.models.ohlcv_dto
import c_infrastructure.database.models.quarter_eps_dto
import c_infrastructure.database.models.trading_journal_dto
import c_infrastructure.database.models.watchlist_dto  # noqa: F401  (each import registers its tables on SQLModel.metadata)
from c_infrastructure.database.db_connector import DatabaseConnector, OutdatedDatabaseError
from c_infrastructure.database.models.schema_version_dto import SCHEMA_VERSION

pytestmark = pytest.mark.asyncio

# trade_signals as stock_agent.db held it before the orders table existed (copied from such a file).
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
    generated_at DATETIME NOT NULL,
    id CHAR(32) NOT NULL,
    PRIMARY KEY (id)
)
"""


def sqlite_layout(path: Path) -> dict[str, list[str]]:
    with sqlite3.connect(path) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {table: [row[1] for row in connection.execute(f"PRAGMA table_info({table})")] for table in tables}


async def init_db(project_root: Path) -> None:
    connector = DatabaseConnector(config=shipped_config(project_root), logger=SilentLogger())

    try:
        await connector.init_db()
    finally:
        await connector.close()


async def test_old_trade_signals_layout_stops_startup_and_stays_untouched(tmp_path: Path) -> None:
    db_path = tmp_path / "stock_agent.db"

    with sqlite3.connect(db_path) as connection:
        connection.execute(OLD_TRADE_SIGNALS)
        connection.execute(
            "INSERT INTO trade_signals VALUES ('2330', 'BUY', 1000.0, 'TECHNICAL', 80, 'old', 1000, NULL, '2026-10-01', 'a1')"
        )

    before = sqlite_layout(db_path)

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    message = str(refused.value)
    assert "trade_signals" in message
    assert "decision_id" in message
    assert f"delete {db_path}" in message
    assert "drop the tables named above" in message
    assert "ohlcv_data" not in message

    assert sqlite_layout(db_path) == before
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT reason FROM trade_signals").fetchall() == [("old",)]


# ohlcv_data as stock_agent.db held it while each bar also stored its session in a trading_date column.
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
    ts DATETIME NOT NULL,
    PRIMARY KEY (stock_id, ts)
)
"""


async def test_old_ohlcv_cache_layout_stops_startup_and_says_the_cache_refills(tmp_path: Path) -> None:
    db_path = tmp_path / "stock_agent.db"

    with sqlite3.connect(db_path) as connection:
        connection.execute(OLD_OHLCV_DATA)

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    message = str(refused.value)
    assert "ohlcv_data (missing columns: none; columns no longer used: trading_date)" in message
    assert "Cached prices and EPS refill themselves" in message


async def test_a_database_the_current_models_created_starts_again(tmp_path: Path) -> None:
    await init_db(tmp_path)
    created = sqlite_layout(tmp_path / "stock_agent.db")

    await init_db(tmp_path)

    assert {"trade_signals", "orders", "workflow_runs", "account_snapshots", "mops_quarter_eps"} <= created.keys()
    assert sqlite_layout(tmp_path / "stock_agent.db") == created
    assert stored_schema_versions(tmp_path / "stock_agent.db") == [SCHEMA_VERSION]


def stored_schema_versions(path: Path) -> list[int]:
    with sqlite3.connect(path) as connection:
        return [row[0] for row in connection.execute("SELECT version FROM schema_version")]


def create_current_tables(path: Path, schema_version: int | None) -> None:
    """Every table with the columns the code declares, as a database an older version wrote would hold them."""
    engine = create_engine(f"sqlite:///{path}")
    tables = [table for table in SQLModel.metadata.sorted_tables if schema_version is not None or table.name != "schema_version"]
    SQLModel.metadata.create_all(engine, tables=tables)
    engine.dispose()

    with sqlite3.connect(path) as connection:
        # An older version stored Taiwan wall-clock time here; the current code would read it as UTC.
        connection.execute(
            "INSERT INTO ohlcv_data (stock_id, ts, open, high, low, close, volume) "
            "VALUES ('2330', '2026-10-30 13:30:00', 1, 1, 1, 1, 1)"
        )

        if schema_version is not None:
            connection.execute("INSERT INTO schema_version (version) VALUES (?)", (schema_version,))


def named_tables(message: str) -> list[str]:
    return [line.removeprefix("  - ").split(" ")[0] for line in message.splitlines() if line.startswith("  - ")]


async def test_a_database_without_a_schema_version_stops_startup_and_stays_untouched(tmp_path: Path) -> None:
    db_path = tmp_path / "stock_agent.db"
    create_current_tables(db_path, schema_version=None)
    before = db_path.read_bytes()

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    message = str(refused.value)
    assert {"ohlcv_data", "trade_signals", "watchlists", "mock_cash"} <= set(named_tables(message))
    assert "schema_version" not in named_tables(message)
    assert f"The database's schema version is none, and this version of stock-agent needs {SCHEMA_VERSION}" in message
    assert f"Remedy: delete {db_path}, or drop the tables named above" in message
    assert "Cached prices and EPS refill themselves" in message
    assert db_path.read_bytes() == before


@pytest.mark.parametrize("schema_version", [0, SCHEMA_VERSION + 1])
async def test_a_database_with_a_schema_version_no_upgrade_reaches_stops_startup_and_stays_untouched(
    tmp_path: Path, schema_version: int
) -> None:
    db_path = tmp_path / "stock_agent.db"
    create_current_tables(db_path, schema_version=schema_version)
    before = db_path.read_bytes()

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    message = str(refused.value)
    assert {"ohlcv_data", "trade_signals", "schema_version"} <= set(named_tables(message))
    assert f"schema version is {schema_version}, and this version of stock-agent needs {SCHEMA_VERSION}" in message
    assert db_path.read_bytes() == before


async def test_dropping_the_named_tables_lets_the_next_start_create_and_stamp_them(tmp_path: Path) -> None:
    db_path = tmp_path / "stock_agent.db"
    create_current_tables(db_path, schema_version=0)

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    with sqlite3.connect(db_path) as connection:
        for table in named_tables(str(refused.value)):
            connection.execute(f"DROP TABLE {table}")

    await init_db(tmp_path)

    assert stored_schema_versions(db_path) == [SCHEMA_VERSION]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ohlcv_data").fetchone() == (0,)


async def test_a_current_database_whose_table_changed_names_only_that_table(tmp_path: Path) -> None:
    db_path = tmp_path / "stock_agent.db"
    await init_db(tmp_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute("ALTER TABLE ohlcv_data ADD COLUMN trading_date DATE")

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    message = str(refused.value)
    assert named_tables(message) == ["ohlcv_data"]
    assert "columns no longer used: trading_date" in message
    assert "schema version" not in message


def version_1_database(path: Path) -> None:
    """
    A database as schema version 1 left it, with rows: workflow_runs had no failure column, and a run stopped by an
    exception kept it only as its "Run aborted: " error. The other tables hold a cached bar, a watchlist entry and cash.
    """
    create_current_tables(path, schema_version=1)

    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE workflow_runs DROP COLUMN failure")
        for run_id, errors in [
            ("a1" * 16, '["Stock not found: 9999", "Run aborted: RuntimeError: Yahoo hung"]'),
            ("b2" * 16, '["Stock not found: 9999"]'),
            ("c3" * 16, '["Run aborted: CancelledError: "]'),
        ]:
            connection.execute(
                "INSERT INTO workflow_runs (run_id, workflow, execution_provider, order_mode, start_time, end_time, "
                "total_scanned, buzz_scanned, buzz_qualified, sentiment_analysed, passed_technical, ai_analysed, "
                "signals_generated, orders_submitted, orders_filled, orders_refused, stale_market_data_count, errors, "
                "execution_log) VALUES (?, 'FULL_CYCLE', 'MOCK', 'MOCK_ONLY', '2026-11-03 06:00:00', "
                "'2026-11-03 06:01:00', 3, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, ?, '[]')",
                (run_id, errors),
            )
        connection.execute("INSERT INTO watchlists (stock_id, type, created_at) VALUES ('2330', 'manual', '2026-11-03 06:00:00')")
        connection.execute(
            "INSERT INTO mock_cash (account_id, current_cash, initial_cash, created_at, updated_at) "
            "VALUES ('local', 990000.0, 1000000.0, '2026-11-03 06:00:00', '2026-11-03 06:00:00')"
        )


def table_rows(path: Path) -> dict[str, list[dict[str, object]]]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")] for table in tables}


async def test_a_version_1_database_is_upgraded_in_place_and_keeps_every_row(tmp_path: Path) -> None:
    db_path = tmp_path / "stock_agent.db"
    version_1_database(db_path)
    before = table_rows(db_path)

    await init_db(tmp_path)

    after = table_rows(db_path)
    current = tmp_path / "current"
    current.mkdir()
    await init_db(current)
    assert sqlite_layout(db_path) == sqlite_layout(current / "stock_agent.db")
    assert stored_schema_versions(db_path) == [SCHEMA_VERSION]
    assert {table: rows for table, rows in after.items() if table not in {"schema_version", "workflow_runs"}} == {
        table: rows for table, rows in before.items() if table not in {"schema_version", "workflow_runs"}
    }
    assert [{**row, "failure": None} for row in before["workflow_runs"]] == [
        {**row, "failure": None} for row in after["workflow_runs"]
    ]
    assert [row["failure"] for row in after["workflow_runs"]] == ["RuntimeError: Yahoo hung", None, "CancelledError: "]
    assert len(before["watchlists"]) == len(before["mock_cash"]) == 1


async def test_a_version_1_database_whose_table_changed_is_refused_and_the_upgrade_rolls_back(tmp_path: Path) -> None:
    db_path = tmp_path / "stock_agent.db"
    version_1_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute("ALTER TABLE ohlcv_data ADD COLUMN trading_date DATE")

    before = sqlite_layout(db_path), table_rows(db_path)

    with pytest.raises(OutdatedDatabaseError) as refused:
        await init_db(tmp_path)

    assert named_tables(str(refused.value)) == ["ohlcv_data"]
    assert (sqlite_layout(db_path), table_rows(db_path)) == before
    assert stored_schema_versions(db_path) == [1]
