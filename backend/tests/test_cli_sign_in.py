"""
The CLI's start and its signed-in session, as a user at the terminal sees them: the first-time administrator setup on an
empty installation, sign-in with its limits, the refusal of a non-administrator, and losing the CLI mid-session.
"""

import io
from collections.abc import Callable, Iterator
from dataclasses import replace
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from rich.console import Console
from rich.prompt import Confirm, Prompt
from support.harness import (
    ADMINISTRATOR,
    ADMINISTRATOR_PASSWORD,
    MARKET_OPEN,
    MEMBER,
    MEMBER_PASSWORD,
    CliHarness,
    build_harness,
    open_harness_switch,
    rising_history,
)

from a_domain.types.enums import Role, UserStatus, WatchlistType
from c_infrastructure.database.models.user_dto import LEGACY_OWNER_ID
from d_presentation.cli import interactive, terminal

pytestmark = pytest.mark.asyncio


@pytest.fixture
def screen(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    output = io.StringIO()
    monkeypatch.setattr(terminal, "console", Console(file=output, width=250))
    return output


def answers(*replies: str) -> Callable[..., str]:
    """A Prompt.ask that gives `replies` in order, the hidden password prompts included, then Ctrl-D at the next prompt."""
    remaining: Iterator[str] = iter(replies)

    def ask(question: str, *args, **kwargs) -> str:
        if (reply := next(remaining, None)) is None:
            raise EOFError

        return reply

    return ask


async def run_cli(harness: CliHarness, monkeypatch: pytest.MonkeyPatch, *replies: str) -> None:
    monkeypatch.setattr(interactive, "open_runtime_switch", lambda: open_harness_switch(harness))

    with patch.object(Prompt, "ask", answers(*replies)), patch.object(Confirm, "ask", lambda *args, **kwargs: False):
        await interactive.interactive_menu()


async def test_the_first_start_sets_up_the_administrator_who_takes_over_the_single_owner_data(
    screen: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = build_harness()
    harness.users.by_id.clear()
    harness.watch("2330", WatchlistType.MANUAL)
    password = "a long new password"

    await run_cli(harness, monkeypatch, "hsiu", "hsiu@example.com", password, password, "0")

    [administrator] = harness.users.by_id.values()
    assert (administrator.user_id, administrator.username, administrator.role) == (LEGACY_OWNER_ID, "hsiu", Role.ADMINISTRATOR)
    assert "Back up secrets/accounts.key with the database now" in screen.getvalue()
    assert "Signed in:          hsiu (administrator)" in screen.getvalue()
    assert [entry.stock_id for entry in (await harness.runtime.pipeline_for(administrator).load_watchlist()).watchlist] == ["2330"]


async def test_the_setup_asks_again_for_a_short_password_or_a_mistyped_second_one(
    screen: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = build_harness()
    harness.users.by_id.clear()

    await run_cli(harness, monkeypatch, "hsiu", "hsiu@example.com", "short", "short", "a long password one", "a long password two")

    assert harness.users.by_id == {}
    assert "A password needs 12 to 256 characters." in screen.getvalue() and "The passwords differ." in screen.getvalue()


async def test_the_administrator_signs_in_with_the_email_in_any_case(screen: io.StringIO, monkeypatch: pytest.MonkeyPatch) -> None:
    await run_cli(build_harness(), monkeypatch, "OWNER@example.com", ADMINISTRATOR_PASSWORD, "0")

    assert "Signed in:          owner (administrator)" in screen.getvalue()


async def test_a_user_who_is_not_an_administrator_gets_no_menu(screen: io.StringIO, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = build_harness()
    harness.users.add(MEMBER, MEMBER_PASSWORD)

    await run_cli(harness, monkeypatch, "member", MEMBER_PASSWORD)

    assert "Only an administrator can use the CLI" in screen.getvalue()
    assert "[1] Run Full Cycle" not in screen.getvalue()


async def test_repeated_wrong_passwords_end_the_cli_at_the_attempt_limit(screen: io.StringIO, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = build_harness()
    limit = harness.config.accounts.sign_in_failures_per_name

    await run_cli(
        harness,
        monkeypatch,
        *(reply for _ in range(limit + 1) for reply in ("owner", "a wrong password")),
        "owner",
        ADMINISTRATOR_PASSWORD,
    )

    assert screen.getvalue().count("Wrong username, email or password.") == limit
    assert "Too many attempts." in screen.getvalue() and "[1] Run Full Cycle" not in screen.getvalue()


async def test_an_administrator_deactivated_mid_session_loses_the_cli_before_the_next_option(
    screen: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.watch("2330", WatchlistType.TECHNICAL)
    replies = iter(["owner", ADMINISTRATOR_PASSWORD])

    def ask(question: str, *args, **kwargs) -> str:
        if question == "Select an option":
            harness.users.by_id[LEGACY_OWNER_ID] = replace(ADMINISTRATOR, status=UserStatus.DEACTIVATED)
            return "3"

        return next(replies)

    monkeypatch.setattr(interactive, "open_runtime_switch", lambda: open_harness_switch(harness))

    with patch.object(Prompt, "ask", ask):
        await interactive.interactive_menu()

    assert "You were signed out" in screen.getvalue()
    assert harness.broker.placed == [] and harness.journal.runs == {}


async def test_the_operators_password_reset_ends_the_users_sessions_and_replaces_the_password() -> None:
    harness = build_harness()
    session = await harness.users.open_session(LEGACY_OWNER_ID, MARKET_OPEN, MARKET_OPEN.replace(year=2027))

    reset = await harness.runtime.signed_out.reset_password("OWNER", SecretStr("a brand new password"))

    assert reset is not None and reset.user_id == LEGACY_OWNER_ID
    assert await harness.users.session_user(session.token, MARKET_OPEN) is None
    assert await harness.users.verify_password("owner", SecretStr(ADMINISTRATOR_PASSWORD)) is None
    assert await harness.users.verify_password("owner", SecretStr("a brand new password")) is not None
    assert await harness.runtime.signed_out.reset_password("nobody", SecretStr("a brand new password")) is None
