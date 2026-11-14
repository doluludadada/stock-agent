"""The decisions of a sign-in with Google, each on its own: the return, the ID token, who is admitted, and the username."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from a_domain.model.system.user import SignInFlow, User
from a_domain.rules.system.google_sign_in import (
    FlowReturnRule,
    GoogleAccessRule,
    GoogleAdmission,
    GoogleUsernameRule,
    IdTokenClaims,
    IdTokenRule,
)
from a_domain.rules.system.registration import SignInOffer
from a_domain.rules.system.settings_change import EditorAccessRule
from a_domain.types.enums import GoogleRefusal, Role, UserStatus
from a_domain.types.ids import UserId

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
FLOW = SignInFlow(
    state="the-state", nonce="the-nonce", code_verifier="the-verifier", started_at=NOW, expires_at=NOW + timedelta(minutes=10)
)
CLAIMS = IdTokenClaims(
    issuer="https://accounts.google.com",
    audiences=("the-client",),
    nonce="the-nonce",
    email="owner@gmail.example",
    email_verified=True,
    expires_at=NOW + timedelta(hours=1),
    authenticated_at=NOW,
)
TOKEN_RULE = IdTokenRule(
    issuers=frozenset({"https://accounts.google.com", "accounts.google.com"}),
    client_id="the-client",
    clock_skew=timedelta(seconds=30),
    fresh_authentication=timedelta(seconds=300),
)
ACCESS = GoogleAccessRule(
    administrator_emails=frozenset({"owner@gmail.example"}),
    allowed_emails=frozenset({"friend@gmail.example"}),
    registration_open=False,
)


def account(
    role: Role, *, has_password: bool = True, status: UserStatus = UserStatus.ACTIVE, email: str = "owner@gmail.example"
) -> User:
    return User(
        user_id=UserId("u-1"), username="someone", email=email, role=role, status=status, created_at=NOW, has_password=has_password
    )


@pytest.mark.parametrize(
    ("offered", "flow", "state", "has_code", "at", "refusal"),
    [
        (True, FLOW, "the-state", True, NOW, None),
        (False, FLOW, "the-state", True, NOW, GoogleRefusal.NOT_OFFERED),
        (True, None, "the-state", True, NOW, GoogleRefusal.FLOW_MISSING),
        (True, FLOW, "the-state", True, FLOW.expires_at, GoogleRefusal.FLOW_MISSING),
        (True, FLOW, "another-state", True, NOW, GoogleRefusal.STATE_MISMATCH),
        (True, FLOW, None, True, NOW, GoogleRefusal.STATE_MISMATCH),
        (True, FLOW, "the-state", False, NOW, GoogleRefusal.CANCELLED),
    ],
)
def test_a_return_belongs_to_the_flow_the_browser_started(
    offered: bool, flow: SignInFlow | None, state: str | None, has_code: bool, at: datetime, refusal: GoogleRefusal | None
) -> None:
    assert FlowReturnRule(offered=offered).apply(flow, state, has_code, at) == refusal


@pytest.mark.parametrize(
    ("change", "confirmation", "refusal"),
    [
        ({}, False, None),
        ({"issuer": "accounts.google.com"}, False, None),
        ({"issuer": "https://accounts.google.com.evil.example"}, False, GoogleRefusal.TOKEN_REFUSED),
        ({"audiences": ("another-client",)}, False, GoogleRefusal.TOKEN_REFUSED),
        ({"audiences": ("the-client", "another-client")}, False, GoogleRefusal.TOKEN_REFUSED),
        ({"audiences": ()}, False, GoogleRefusal.TOKEN_REFUSED),
        ({"nonce": "another-nonce"}, False, GoogleRefusal.TOKEN_REFUSED),
        ({"nonce": ""}, False, GoogleRefusal.TOKEN_REFUSED),
        ({"expires_at": NOW - timedelta(seconds=30)}, False, GoogleRefusal.TOKEN_REFUSED),
        ({"expires_at": NOW - timedelta(seconds=29)}, False, None),
        ({"email_verified": False}, False, GoogleRefusal.EMAIL_UNVERIFIED),
        ({"authenticated_at": None}, False, None),
        ({"authenticated_at": NOW - timedelta(days=30)}, False, None),
        ({"authenticated_at": None}, True, GoogleRefusal.STALE_AUTHENTICATION),
        ({"authenticated_at": NOW - timedelta(seconds=331)}, True, GoogleRefusal.STALE_AUTHENTICATION),
        ({"authenticated_at": NOW - timedelta(seconds=330)}, True, None),
    ],
)
def test_an_id_token_is_this_apps_own_answer_to_the_flow(change: dict, confirmation: bool, refusal: GoogleRefusal | None) -> None:
    assert TOKEN_RULE.apply(replace(CLAIMS, **change), "the-nonce", confirmation, NOW) == refusal


@pytest.mark.parametrize(
    ("email", "existing", "user_count", "result"),
    [
        ("owner@gmail.example", None, 0, GoogleAdmission(role=Role.ADMINISTRATOR, keeps_password=False)),
        ("owner@gmail.example", account(Role.ADMINISTRATOR), 1, GoogleAdmission(role=Role.ADMINISTRATOR, keeps_password=True)),
        ("owner@gmail.example", account(Role.USER), 2, GoogleAdmission(role=Role.ADMINISTRATOR, keeps_password=False)),
        ("owner@gmail.example", account(Role.ADMINISTRATOR, status=UserStatus.DEACTIVATED), 2, GoogleRefusal.DEACTIVATED),
        ("friend@gmail.example", None, 1, GoogleAdmission(role=Role.USER, keeps_password=False)),
        ("friend@gmail.example", None, 0, GoogleRefusal.NOT_ALLOWED),
        ("friend@gmail.example", account(Role.USER), 2, GoogleAdmission(role=Role.USER, keeps_password=False)),
        ("friend@gmail.example", account(Role.ADMINISTRATOR), 2, GoogleAdmission(role=Role.ADMINISTRATOR, keeps_password=True)),
        ("stranger@gmail.example", None, 1, GoogleRefusal.NOT_ALLOWED),
        ("stranger@gmail.example", account(Role.USER), 2, GoogleRefusal.NOT_ALLOWED),
        ("owner@gmail.example.evil.example", None, 1, GoogleRefusal.NOT_ALLOWED),
        ("gmail.example", None, 1, GoogleRefusal.NOT_ALLOWED),
    ],
)
def test_who_signs_in_with_google_and_as_what(
    email: str, existing: User | None, user_count: int, result: GoogleAdmission | GoogleRefusal
) -> None:
    assert ACCESS.apply(email, existing, user_count) == result


def test_open_registration_admits_any_verified_email_as_a_user_once_an_administrator_exists() -> None:
    open_access = replace(ACCESS, registration_open=True)

    assert open_access.apply("stranger@gmail.example", None, 1) == GoogleAdmission(role=Role.USER, keeps_password=False)
    assert open_access.apply("stranger@gmail.example", None, 0) == GoogleRefusal.NOT_ALLOWED


@pytest.mark.parametrize(
    ("email", "taken", "username"),
    [
        ("shiou.lin@gmail.example", False, "shiou.lin"),
        ("shiou.lin@gmail.example", True, "shiou.lin-0123abcd"),
        ("a+b@gmail.example", False, "ab-0123abcd"),
        ("._-x@gmail.example", False, "x-0123abcd"),
        ("+@gmail.example", False, "user-0123abcd"),
        (f"{'a' * 40}@gmail.example", False, "a" * 32),
        (f"{'a' * 40}@gmail.example", True, f"{'a' * 23}-0123abcd"),
    ],
)
def test_a_created_username_is_always_one_a_username_may_be(email: str, taken: bool, username: str) -> None:
    created = GoogleUsernameRule().apply(email, UserId("0123abcd4567"), taken)

    assert created == username
    assert account(Role.USER).username and replace(account(Role.USER), username=created).username == username


def test_new_settings_must_still_admit_an_administrator_who_has_no_password() -> None:
    offer = SignInOffer(needs_first_administrator=False, registration_open=False, google_sign_in=True)
    google_only, with_password = account(Role.ADMINISTRATOR, has_password=False), account(Role.ADMINISTRATOR)
    without_google = EditorAccessRule()
    another_list = EditorAccessRule(google_access=replace(ACCESS, administrator_emails=frozenset({"other@gmail.example"})))

    assert EditorAccessRule(google_access=ACCESS).apply(offer, offer, google_only.user_id, google_only) is None
    assert "no password" in (without_google.apply(offer, offer, google_only.user_id, google_only) or "")
    assert "no password" in (another_list.apply(offer, offer, google_only.user_id, google_only) or "")
    assert without_google.apply(offer, offer, with_password.user_id, with_password) is None
