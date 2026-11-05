from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr, TypeAdapter, ValidationError

from a_domain.model.system.user import User
from a_domain.ports.system.attempt_log import AttemptKey
from a_domain.rules.system.attempt_limit import AttemptLimitRule
from a_domain.types.enums import AttemptLimit, Permission, Role, UserStatus
from a_domain.types.ids import UserId
from a_domain.types.values import EmailAddress, NewPassword, Username
from c_infrastructure.system.attempt_log import MemoryAttemptLog

NOON = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
WINDOW = timedelta(minutes=15)


def test_an_administrator_holds_every_permission_and_a_user_none() -> None:
    assert Role.ADMINISTRATOR.permissions == frozenset(Permission)
    assert Role.USER.permissions == frozenset()


@pytest.mark.parametrize("username", ["alice", "Alice.B_c-1", "a1b"])
def test_a_username_of_3_to_32_letters_digits_and_dot_dash_underscore_is_accepted(username: str) -> None:
    assert TypeAdapter(Username).validate_python(username) == username


@pytest.mark.parametrize("username", ["alice@example.com", "ab", "a" * 33, "-alice", "al ice", ""])
def test_a_username_with_an_at_sign_or_outside_the_shape_is_refused(username: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Username).validate_python(username)


@pytest.mark.parametrize("email", ["no-at-sign", "two@@example.com", "a@b", "a b@example.com"])
def test_an_email_without_the_shape_of_one_is_refused(email: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(EmailAddress).validate_python(email)


def test_a_password_needs_12_to_256_characters_and_never_shows_in_a_repr() -> None:
    adapter = TypeAdapter(NewPassword)

    with pytest.raises(ValidationError):
        adapter.validate_python("x" * 11)

    with pytest.raises(ValidationError):
        adapter.validate_python("x" * 257)

    password = adapter.validate_python("correct horse")
    assert isinstance(password, SecretStr)
    assert "correct horse" not in repr(password)


def test_a_user_refuses_a_username_with_an_at_sign_on_assignment() -> None:
    user = User(user_id=UserId("u1"), username="alice", email="alice@example.com", role=Role.USER, created_at=NOON)

    with pytest.raises(ValidationError):
        user.username = "alice@example.com"

    assert user.username == "alice"
    assert user.status == UserStatus.ACTIVE


def test_the_attempt_limit_refuses_the_attempt_after_the_maximum_until_the_oldest_leaves_the_window() -> None:
    rule = AttemptLimitRule(max_attempts=5, window=WINDOW)
    failures = [NOON - timedelta(minutes=minutes) for minutes in (14, 10, 6, 3, 1)]

    assert rule.apply(failures[:4], NOON) is None
    assert rule.apply(failures, NOON) == NOON - timedelta(minutes=14) + WINDOW


@pytest.mark.asyncio
async def test_the_attempt_log_returns_the_earlier_attempts_inside_their_window() -> None:
    log, key = MemoryAttemptLog(), AttemptKey(limit=AttemptLimit.SIGN_IN_CLIENT, client="203.0.113.7")

    assert await log.record(key, NOON - WINDOW, WINDOW) == []
    assert await log.record(key, NOON - timedelta(minutes=1), WINDOW) == [NOON - WINDOW]
    assert await log.record(key, NOON, WINDOW) == [NOON - timedelta(minutes=1)]


@pytest.mark.asyncio
async def test_the_attempt_log_takes_back_one_attempt_and_clears_a_key() -> None:
    log = MemoryAttemptLog()
    name, client = (
        AttemptKey(limit=limit, client="203.0.113.7", name="Alice")
        for limit in (AttemptLimit.SIGN_IN_NAME, AttemptLimit.SIGN_IN_CLIENT)
    )
    await log.record(name, NOON, WINDOW)
    await log.record(client, NOON, WINDOW)
    await log.forget(client, NOON)
    await log.clear(name)

    assert await log.record(name, NOON, WINDOW) == []
    assert await log.record(client, NOON, WINDOW) == []


def test_a_sign_in_name_key_compares_the_name_as_sign_in_does() -> None:
    assert AttemptKey(limit=AttemptLimit.SIGN_IN_NAME, client="cli", name=" ＡＬＩＣＥ") == AttemptKey(
        limit=AttemptLimit.SIGN_IN_NAME, client="cli", name="alice"
    )


@pytest.mark.asyncio
async def test_the_attempt_log_forgets_keys_never_asked_again() -> None:
    """
    Rotating addresses: an address's attempt leaves the log after its window, asked again or not, by the time as many
    new addresses wrote. The log's keys are read directly: what it keeps is the behavior under test.
    """
    log = MemoryAttemptLog()

    for client in range(1000):
        await log.record(AttemptKey(limit=AttemptLimit.REGISTRATION, client=f"10.0.{client // 256}.{client % 256}"), NOON, WINDOW)

    for client in range(1000):
        await log.record(
            AttemptKey(limit=AttemptLimit.REGISTRATION, client=f"10.1.{client // 256}.{client % 256}"), NOON + WINDOW, WINDOW
        )

    assert {key.client.split(".")[1] for key in log._attempts} == {"1"}
