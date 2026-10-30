"""DatabaseConnector.init_db() against real SQLite files: it refuses an old table layout and never changes it."""

import sqlite3
from pathlib import Path

import pytest
from trading_stack import SilentLogger

import c_infrastructure.database.models.article_dto
import c_infrastructure.database.models.mock_trading_dto
import c_infrastructure.database.models.ohlcv_dto
import c_infrastructure.database.models.quarter_eps_dto
import c_infrastructure.database.models.trading_journal_dto
import c_infrastructure.database.models.watchlist_dto  # noqa: F401  (each import registers its tables on SQLModel.metadata)
from b_application.schemas.config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector, OutdatedDatabaseError

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
    connector = DatabaseConnector(config=AppConfig(project_root=project_root), logger=SilentLogger())

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
