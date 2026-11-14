"""Fixtures any test module may ask for by name."""

import importlib
import os
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from support.databases import ENVIRONMENT, TestDatabase, open_database

from c_infrastructure.database.db_connector import DatabaseConnector
from d_presentation.dependencies import import_shioaji

os.environ.update(ENVIRONMENT)
"""Before any test module reads the settings: every configuration a test builds names the session's own database."""

import_shioaji()
shioaji = importlib.import_module("shioaji")
"""The SDK, imported first the app's way, so the suite writes no shioaji.log into the working directory either."""


@pytest.fixture(autouse=True)
def no_sinopac(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    No test reaches Sinopac: a personal runtime with a Shioaji key pair in the environment or .env would log in for
    its realtime quotes. A test that needs a client patches shioaji.Shioaji with support.fake_shioaji.FakeShioaji.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test built a real Shioaji client: patch shioaji.Shioaji with FakeShioaji")

    monkeypatch.setattr(shioaji, "Shioaji", refuse)


@pytest.fixture
def server_in_utc(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The process's own time zone is UTC, as in the deployed container, and the machine's again after the test."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture(scope="session")
def test_database() -> Iterator[TestDatabase]:
    """The session's own PostgreSQL database, created here and dropped when the session ends."""
    session_database = TestDatabase()
    session_database.create()
    yield session_database
    session_database.drop()


@pytest.fixture(autouse=True)
def empty_test_database(test_database: TestDatabase) -> None:
    """Every test starts on an empty database: what the test before it created is dropped first."""
    test_database.empty()


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[DatabaseConnector]:
    """The session's database with every table created, closed after the test."""
    connector = open_database(tmp_path)
    await connector.init_db()
    yield connector
    await connector.close()
