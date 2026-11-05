"""Fixtures any test module may ask for by name."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from support.databases import BACKENDS, empty_database

from a_domain.types.enums import DatabaseBackend
from c_infrastructure.database.db_connector import DatabaseConnector


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
