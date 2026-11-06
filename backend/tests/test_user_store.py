"""
SqlUserStore over a real database of each backend: what an operator and a user can observe of the stored credentials,
the sessions and the last-administrator guarantee.
"""

import asyncio
import base64
import secrets
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from argon2 import PasswordHasher
from cryptography.exceptions import InvalidTag
from pydantic import SecretStr
from sqlalchemy import text, update
from sqlmodel import col
from support.databases import raw_engine
from support.settings import shipped_config
from trading_stack import SilentLogger

from a_domain.model.system.user import User
from a_domain.types.enums import AiProvider, DatabaseBackend, Role, UserStatus
from a_domain.types.errors import AlreadySetUpError, LastAdministratorError, SignInRefused, SignInThrottled, UserExistsError
from a_domain.types.ids import SessionToken, UserId
from b_application.use_cases.users.sign_in_attempt import SignInAttempt
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.user_dto import UserDTO
from c_infrastructure.database.repositories.user_store import AccountsKeyError, SqlUserStore
from c_infrastructure.system.attempt_log import MemoryAttemptLog

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
PASSWORD = SecretStr("correct horse battery")


def new_key() -> SecretStr:
    return SecretStr(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))


KEY = new_key()


def user(user_id: str, username: str, email: str, role: Role = Role.USER) -> User:
    return User(user_id=UserId(user_id), username=username, email=email, role=role, created_at=NOW)


@pytest_asyncio.fixture
async def store(database: DatabaseConnector) -> SqlUserStore:
    store = SqlUserStore(database, KEY, SilentLogger())
    await store.create(user("local", "Alice", "Alice@Example.com", Role.ADMINISTRATOR), PASSWORD)
    await store.create(user("u-2", "bob", "bob@example.com"), PASSWORD)
    return store


@pytest.mark.asyncio
async def test_a_username_or_email_is_taken_whatever_its_case(store: SqlUserStore) -> None:
    with pytest.raises(UserExistsError) as username:
        await store.create(user("u-1", "ALICE", "new@example.com"), PASSWORD)

    with pytest.raises(UserExistsError) as email:
        await store.create(user("u-2", "carol", "alice@EXAMPLE.com"), PASSWORD)

    with pytest.raises(AlreadySetUpError):
        await store.create(user("local", "dave", "dave@example.com", Role.ADMINISTRATOR), PASSWORD)

    assert (username.value.field, email.value.field) == ("username", "email")
    assert await store.user_count() == 2


@pytest.mark.asyncio
async def test_a_user_signs_in_with_the_username_or_the_email_in_any_case(store: SqlUserStore) -> None:
    by_name = await store.verify_password("aLiCe", PASSWORD)
    by_email = await store.verify_password("ALICE@example.COM", PASSWORD)

    assert by_name == by_email
    assert by_name is not None and (by_name.username, by_name.email, by_name.role) == (
        "Alice",
        "Alice@Example.com",
        Role.ADMINISTRATOR,
    )


class WallClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@pytest.mark.asyncio
async def test_wrong_passwords_sent_at_once_are_refused_after_the_limit(store: SqlUserStore) -> None:
    """The shipped limits: 5 failures per sign-in name and client, 20 per client. A burst cannot pass them together."""
    sign_in = SignInAttempt(store, MemoryAttemptLog(), WallClock(), shipped_config(), SilentLogger())

    async def guess(number: int, name: str = "alice") -> type[Exception]:
        try:
            await sign_in.execute(name, SecretStr(f"wrong guess {number}"), "203.0.113.7")
        except (SignInRefused, SignInThrottled) as refused:
            return type(refused)

        raise AssertionError("a wrong password signed in")

    outcomes = await asyncio.gather(*(guess(number) for number in range(30)))
    variants = await asyncio.gather(*(guess(number, name) for number, name in enumerate(["ＡＬＩＣＥ", " Alice", "ALICE"])))

    assert (outcomes.count(SignInRefused), outcomes.count(SignInThrottled)) == (5, 25)
    assert set(variants) == {SignInThrottled}
    assert (await sign_in.execute("alice", PASSWORD, "198.51.100.1")).user_id == "local"


@pytest.mark.asyncio
async def test_sign_ins_waiting_for_the_password_hash_hold_no_database_connection(
    backend: DatabaseBackend, database: DatabaseConnector, store: SqlUserStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """More sign-ins than the pool has connections wait on the hash at once, and another request still reads at once."""
    hashing, release = threading.Event(), threading.Event()

    class SlowHasher(PasswordHasher):
        def verify(self, hash: str | bytes, password: str | bytes) -> bool:
            hashing.set()
            release.wait(timeout=60)
            return super().verify(hash, password)

    monkeypatch.setattr(store, "_hasher", SlowHasher(time_cost=2, memory_cost=19_456, parallelism=1))
    burst = [asyncio.create_task(store.verify_password("alice", SecretStr(f"guess {number}"))) for number in range(40)]
    await asyncio.to_thread(hashing.wait, 30)

    try:
        async with database.get_session() as session:
            assert await asyncio.wait_for(session.scalar(text("SELECT 1")), timeout=10) == 1
    finally:
        release.set()
        await asyncio.gather(*burst)


@pytest.mark.asyncio
async def test_an_unknown_name_and_a_wrong_password_get_the_same_answer(store: SqlUserStore) -> None:
    assert await store.verify_password("nobody", PASSWORD) is None
    assert await store.verify_password("alice", SecretStr("wrong password here")) is None


@pytest.mark.asyncio
async def test_the_database_holds_no_username_email_or_password_in_the_clear(
    backend: DatabaseBackend, database: DatabaseConnector, store: SqlUserStore, tmp_path: Path
) -> None:
    engine = raw_engine(backend, tmp_path)

    async with engine.connect() as connection:
        rows = (await connection.execute(text("SELECT * FROM users"))).all()

    await engine.dispose()
    stored = repr(rows).lower()

    assert not any(secret in stored for secret in ("alice", "example.com", "bob", PASSWORD.get_secret_value()))
    assert all("$argon2id$v=19$m=19456,t=2,p=1$" in str(row) for row in rows)


@pytest.mark.asyncio
async def test_a_sealed_email_moved_onto_another_user_does_not_open(
    backend: DatabaseBackend, database: DatabaseConnector, store: SqlUserStore
) -> None:
    async with database.get_session() as session:
        alices = await session.get_one(UserDTO, "local")
        await session.execute(update(UserDTO).where(col(UserDTO.user_id) == "u-2").values(email_sealed=alices.email_sealed))
        await session.commit()

    with pytest.raises(InvalidTag):
        await store.find(UserId("u-2"))


@pytest.mark.asyncio
async def test_a_session_works_until_it_expires_or_its_user_is_deactivated(store: SqlUserStore) -> None:
    session = await store.open_session(UserId("u-2"), NOW, NOW + timedelta(days=14))
    bob = await store.session_user(session.token, NOW)

    assert bob is not None and bob.username == "bob"
    assert await store.session_user(session.token, NOW + timedelta(days=14)) is None
    assert await store.session_user(SessionToken("forged"), NOW) is None

    bob.status = UserStatus.DEACTIVATED
    await store.save(bob, NOW)
    bob.status = UserStatus.ACTIVE
    await store.save(bob, NOW)

    assert await store.session_user(session.token, NOW) is None
    assert await store.verify_password("bob", PASSWORD) is not None


@pytest.mark.asyncio
async def test_signing_out_ends_only_that_session(store: SqlUserStore) -> None:
    first = await store.open_session(UserId("u-2"), NOW, NOW + timedelta(days=1))
    second = await store.open_session(UserId("u-2"), NOW, NOW + timedelta(days=1))
    await store.close_session(first.token)
    await store.close_session(first.token)

    assert await store.session_user(first.token, NOW) is None
    assert await store.session_user(second.token, NOW) is not None


@pytest.mark.asyncio
async def test_a_refused_change_keeps_the_old_role_and_password_and_a_saved_one_ends_the_sessions(store: SqlUserStore) -> None:
    alice = await store.find(UserId("local"))
    bob = await store.find(UserId("u-2"))
    assert alice is not None and bob is not None
    session = await store.open_session(bob.user_id, NOW, NOW + timedelta(days=1))
    alice.role = Role.USER

    with pytest.raises(LastAdministratorError):
        await store.save(alice, NOW, SecretStr("a new password for alice"))

    await store.save(bob, NOW, SecretStr("a new password for bob"))

    assert await store.verify_password("alice", PASSWORD) is not None
    assert await store.verify_password("alice", SecretStr("a new password for alice")) is None
    assert (await store.find(UserId("local"))).role == Role.ADMINISTRATOR
    assert await store.verify_password("bob", SecretStr("a new password for bob")) is not None
    assert await store.session_user(session.token, NOW) is None


@pytest.mark.asyncio
async def test_a_users_ai_model_and_an_administrators_change_of_their_role_never_undo_each_other(store: SqlUserStore) -> None:
    read_before_the_choice = await store.find(UserId("u-2"))
    assert read_before_the_choice is not None and read_before_the_choice.ai_model is None
    await store.save_ai_model(UserId("u-2"), AiProvider.OPENAI, NOW)
    read_before_the_choice.role = Role.ADMINISTRATOR
    await store.save(read_before_the_choice, NOW)
    chosen = await store.find(UserId("u-2"))

    read_before_the_demotion = await store.find(UserId("u-2"))
    assert read_before_the_demotion is not None
    await store.save(replace(read_before_the_demotion, role=Role.USER), NOW)
    await store.save_ai_model(UserId("u-2"), None, NOW)
    cleared = await store.find(UserId("u-2"))

    assert chosen is not None and (chosen.role, chosen.ai_model) == (Role.ADMINISTRATOR, AiProvider.OPENAI)
    assert cleared is not None and (cleared.role, cleared.ai_model) == (Role.USER, None)


@pytest.mark.asyncio
async def test_a_deactivated_user_cannot_sign_in(store: SqlUserStore) -> None:
    bob = await store.find(UserId("u-2"))
    assert bob is not None
    bob.status = UserStatus.DEACTIVATED
    await store.save(bob, NOW)

    assert await store.verify_password("bob", PASSWORD) is None


@pytest.mark.asyncio
async def test_the_last_active_administrator_can_be_neither_demoted_nor_deactivated(store: SqlUserStore) -> None:
    for change in ({"role": Role.USER}, {"status": UserStatus.DEACTIVATED}):
        alice = await store.find(UserId("local"))
        assert alice is not None

        for field, value in change.items():
            setattr(alice, field, value)

        with pytest.raises(LastAdministratorError):
            await store.save(alice, NOW)

    assert [(found.username, found.role, found.status) for found in await store.users()] == [
        ("Alice", Role.ADMINISTRATOR, UserStatus.ACTIVE),
        ("bob", Role.USER, UserStatus.ACTIVE),
    ]


@pytest.mark.asyncio
async def test_two_administrators_demoting_each_other_at_once_leave_one(
    backend: DatabaseBackend, database: DatabaseConnector, store: SqlUserStore
) -> None:
    bob = await store.find(UserId("u-2"))
    assert bob is not None
    bob.role = Role.ADMINISTRATOR
    await store.save(bob, NOW)
    demoted = [await store.find(UserId("local")), await store.find(UserId("u-2"))]

    for administrator in demoted:
        assert administrator is not None
        administrator.role = Role.USER

    results = await asyncio.gather(
        *(store.save(administrator, NOW) for administrator in demoted if administrator), return_exceptions=True
    )
    refused = [result for result in results if isinstance(result, Exception)]

    assert len(refused) == 1
    assert backend == DatabaseBackend.SQLITE or isinstance(refused[0], LastAdministratorError)
    assert [found.role for found in await store.users()].count(Role.ADMINISTRATOR) == 1


@pytest.mark.asyncio
async def test_a_hash_of_older_parameters_is_replaced_at_sign_in(
    backend: DatabaseBackend, database: DatabaseConnector, store: SqlUserStore
) -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD.get_secret_value())

    async with database.get_session() as session:
        await session.execute(update(UserDTO).where(col(UserDTO.user_id) == "u-2").values(password_hash=weak))
        await session.commit()

    assert await store.verify_password("bob", PASSWORD) is not None

    async with database.get_session() as session:
        assert "m=19456,t=2,p=1" in (await session.get_one(UserDTO, "u-2")).password_hash


@pytest.mark.asyncio
async def test_startup_refuses_another_key_than_the_users_were_saved_with(
    store: SqlUserStore, backend: DatabaseBackend, database: DatabaseConnector
) -> None:
    await store.check_key()

    with pytest.raises(AccountsKeyError, match="Restore the original secrets/accounts.key"):
        await SqlUserStore(database, new_key(), SilentLogger()).check_key()
