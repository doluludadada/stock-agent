"""db.backend alone chooses the database. PostgreSQL credentials in the environment never switch it."""

import pytest
from pydantic import ValidationError
from support.settings import shipped_config

from a_domain.types.enums import DatabaseBackend

CREDENTIALS = {"DB_USER": "service", "DB_PASSWORD": "secret", "DB_HOST": "db.example", "DB_NAME": "stock_agent"}


def test_sqlite_refuses_to_start_with_every_postgresql_credential_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in CREDENTIALS.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match="Choose the database with db.backend"):
        shipped_config()


@pytest.mark.parametrize("blank", list(CREDENTIALS))
def test_sqlite_starts_when_a_postgresql_credential_is_blank(blank: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in CREDENTIALS.items():
        monkeypatch.setenv(name, "" if name == blank else value)

    assert shipped_config().db.backend == DatabaseBackend.SQLITE
