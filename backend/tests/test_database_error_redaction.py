"""
What an error of the database says of the values a statement was given, on the real database: nothing, in the error
the engine raises, in the driver's error it chains to, and so in a traceback, whichever way PostgreSQL or the driver
quotes a refused value.
"""

import traceback

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from c_infrastructure.database.db_connector import DatabaseConnector

pytestmark = pytest.mark.asyncio

SECRET = "hunter2-secret"


@pytest.mark.parametrize(
    ("statement", "says"),
    [
        pytest.param("SELECT CAST(:value AS integer) + 1", "DataError", id="the driver refuses the value's type"),
        pytest.param("SELECT CAST(CAST(:value AS text) AS integer)", "SQLSTATE 22P02", id="the server refuses the value's text"),
        pytest.param("SELECT CAST(CAST(:value AS text) AS date)", "SQLSTATE 22007", id="the server refuses the value as a date"),
        pytest.param(
            "INSERT INTO technical_settings (owner_id, active_strategy_id, revision) VALUES (:value, 'a', 1), (:value, 'a', 1)",
            "UniqueViolationError",
            id="the server quotes the refused key in its detail",
        ),
    ],
)
async def test_a_refused_statement_never_says_the_value_it_was_given(database: DatabaseConnector, statement: str, says: str) -> None:
    with pytest.raises(DBAPIError) as refused:
        async with database.get_session() as session:
            await session.execute(text(statement), {"value": SECRET})

    printed = "".join(traceback.format_exception(refused.value))
    assert SECRET not in printed
    assert says in str(refused.value)
    assert "[SQL: " in str(refused.value)
