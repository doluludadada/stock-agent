"""Fixtures any test module may ask for by name."""

import importlib
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from support.databases import BACKENDS, empty_database

from a_domain.types.enums import DatabaseBackend
from c_infrastructure.database.db_connector import DatabaseConnector
from d_presentation.dependencies import import_shioaji

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


@pytest.fixture(params=BACKENDS)
def backend(request: pytest.FixtureRequest) -> DatabaseBackend:
    """Each database backend: SQLite always, PostgreSQL when STOCK_AGENT_TEST_POSTGRES_URL is set."""
    return request.param


@pytest_asyncio.fixture
async def database(backend: DatabaseBackend, tmp_path: Path) -> AsyncIterator[DatabaseConnector]:
    """An empty database of the backend with every table created, closed after the test."""
    connector = await empty_database(backend, tmp_path)
    await connector.init_db()
    yield connector
    await connector.close()
