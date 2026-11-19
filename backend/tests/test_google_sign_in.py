"""
Sign-in with Google over the Web API, against a stand-in for Google's endpoints: who it admits and as what, what it
refuses and why, the settings confirmation of an administrator without a password, its limits, and what it keeps out of
the logs and the answers.
"""

import logging
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr
from support.fake_google import FakeGoogle
from support.harness import ADMINISTRATOR, ADMINISTRATOR_PASSWORD, MEMBER, MEMBER_PASSWORD, CliHarness, build_harness, harness_config
from support.web import app_of, client_at, sign_in

from a_domain.model.system.user import User
from a_domain.types.enums import Role, UserStatus
from a_domain.types.ids import UserId
from b_application.config.settings_loader import InvalidSettingsError, startup_settings
from c_infrastructure.identity.google_identity_provider import GoogleIdentityProvider
from d_presentation.dependencies import compose_runtime

pytestmark = pytest.mark.asyncio

CLIENT_ID = "stock-agent-client.apps.example"
CLIENT_SECRET = "the-client-secret-of-the-test"
ORIGIN = "http://127.0.0.1"
ISSUER = "https://google.test"
OWNER_EMAIL = "Owner.Gmail@Example.com"
START = "/v1/auth/google/start"
CONFIRMATION = "c0nfirmation-id-0123456789"
REPOSITORY_CONFIG = Path(__file__).resolve().parents[2] / "config"


def google_harness(
    *,
    administrators: tuple[str, ...] = (OWNER_EMAIL,),
    allowed: tuple[str, ...] = (),
    registration_open: bool = False,
    settings_root: Path | None = None,
) -> tuple[CliHarness, FakeGoogle]:
    """A harness whose site offers sign-in with Google, with the real adapter talking to the stand-in's token endpoint."""
    shipped = harness_config()
    accounts = shipped.accounts.model_copy(
        update={
            "google_client_id": CLIENT_ID,
            "google_client_secret": SecretStr(CLIENT_SECRET),
            "public_origin": ORIGIN,
            "google_administrator_emails": administrators,
            "google_allowed_emails": allowed,
            "registration_open": registration_open,
            "google_issuer": ISSUER,
            "google_authorization_endpoint": f"{ISSUER}/authorize",
            "google_token_endpoint": f"{ISSUER}/token",
        }
    )
    config = shipped.model_copy(update={"accounts": accounts})
    harness = build_harness(config=config) if settings_root is None else build_harness(config=config, settings_root=settings_root)
    google = FakeGoogle(CLIENT_ID, CLIENT_SECRET, ISSUER, now=harness.clock.now)
    harness.dependencies.identity_provider = GoogleIdentityProvider(
        client_id=CLIENT_ID,
        client_secret=SecretStr(CLIENT_SECRET),
        authorization_endpoint=f"{ISSUER}/authorize",
        token_endpoint=f"{ISSUER}/token",
        timeout_seconds=5,
        transport=httpx.ASGITransport(app=google.app),
    )
    harness.runtime = compose_runtime(harness.config, harness.logger, harness.clock, harness.dependencies)
    return harness, google


async def started(client: httpx.AsyncClient, **query: str) -> str:
    """The browser's navigation to the start: Google's address it is redirected to. The client keeps the flow cookie."""
    response = await client.get(START, params=query)
    assert response.status_code == 303, response.text
    return response.headers["location"]


async def returned(client: httpx.AsyncClient, callback: str) -> httpx.Response:
    """The browser follows Google's redirect back to the callback."""
    return await client.get(callback.removeprefix(ORIGIN))


async def signed_in_with_google(client: httpx.AsyncClient, google: FakeGoogle, email: str) -> httpx.Response:
    return await returned(client, google.approve(await started(client), email))


def outcome_of(response: httpx.Response) -> tuple[str, str | None]:
    """Where the callback sent the browser, and what ?google= says."""
    assert response.status_code == 303, response.text
    location = urlsplit(response.headers["location"])
    return location.path, parse_qs(location.query).get("google", [None])[0]


def said(harness: CliHarness, response: httpx.Response | None = None) -> str:
    """Everything a log line or an answer said."""
    logged = "\n".join(message for _, message in harness.logger.records)
    return logged if response is None else f"{logged}\n{response.headers}\n{response.text}"


async def test_the_status_offers_google_only_with_the_client_and_the_origin() -> None:
    harness, _ = google_harness()

    async with app_of(harness) as app, client_at(app) as client:
        offered = (await client.get("/v1/auth/status")).json()

    async with app_of(build_harness()) as app, client_at(app) as client:
        plain = (await client.get("/v1/auth/status")).json()
        start = await client.get(START)

    assert (offered["google_sign_in"], plain["google_sign_in"]) == (True, False)
    assert outcome_of(start) == ("/sign-in", "not_offered")


async def test_the_start_redirects_to_google_with_state_nonce_and_pkce_and_sets_only_the_flow_cookie() -> None:
    harness, _ = google_harness()

    async with app_of(harness) as app, client_at(app) as client:
        response = await client.get(START)

    address = urlsplit(response.headers["location"])
    query = {name: values[0] for name, values in parse_qs(address.query).items()}
    cookie = response.headers["set-cookie"]
    assert f"{address.scheme}://{address.netloc}{address.path}" == f"{ISSUER}/authorize"
    assert query["redirect_uri"] == f"{ORIGIN}/v1/auth/google/callback" and query["client_id"] == CLIENT_ID
    assert query["response_type"] == "code" and query["code_challenge_method"] == "S256" and query["scope"] == "openid email"
    assert min(len(query["state"]), len(query["nonce"]), len(query["code_challenge"])) >= 43
    assert "max_age" not in query and "client_secret" not in query
    assert cookie.startswith("stock_agent_google_flow=") and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Path=/v1/auth/google" in cookie and "Max-Age=600" in cookie
    assert response.headers["cache-control"] == "no-store" and response.headers["referrer-policy"] == "no-referrer"


async def test_the_redirect_uri_comes_from_the_public_origin_never_from_the_host_header() -> None:
    harness, _ = google_harness()
    harness.config.api.allowed_hosts = ("127.0.0.1", "localhost")

    async with app_of(harness) as app:
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")

        async with client:
            address = await started(client)

    assert parse_qs(urlsplit(address).query)["redirect_uri"] == [f"{ORIGIN}/v1/auth/google/callback"]


async def test_an_administrator_email_sets_up_an_empty_installation_and_is_signed_in() -> None:
    harness, google = google_harness()
    harness.users.by_id.clear()

    async with app_of(harness) as app, client_at(app) as client:
        before = (await client.get("/v1/auth/status")).json()
        response = await signed_in_with_google(client, google, OWNER_EMAIL)
        me = (await client.get("/v1/auth/me")).json()
        after = (await client.get("/v1/auth/status")).json()
        setup = await client.post(
            "/v1/auth/setup",
            json={
                "username": "other",
                "email": "o@example.com",
                "password": "a long first password",
                "setup_code": app.state.setup_code,
            },
        )

    session = next(header for header in response.headers.get_list("set-cookie") if header.startswith("stock_agent_session="))
    assert outcome_of(response) == ("/", None)
    assert "HttpOnly" in session and "SameSite=strict" in session and "Path=/v1" in session
    assert (before["needs_first_administrator"], after["needs_first_administrator"]) == (True, False)
    assert (me["user_id"], me["username"], me["email"], me["role"]) == (
        ADMINISTRATOR.user_id,
        "Owner.Gmail",
        OWNER_EMAIL,
        "administrator",
    )
    assert me["has_password"] is False and "edit_system_settings" in me["permissions"]
    assert setup.status_code == 409


async def test_the_setup_code_still_sets_up_an_installation_that_offers_google() -> None:
    harness, _ = google_harness()
    harness.users.by_id.clear()
    setup = {"username": "hsiu", "email": "hsiu@example.com", "password": "a long first password"}

    async with app_of(harness) as app, client_at(app) as client:
        created = await client.post("/v1/auth/setup", json={**setup, "setup_code": app.state.setup_code})
        signed_in = await sign_in(client, "hsiu", setup["password"])

    assert (created.status_code, signed_in.status_code, signed_in.json()["has_password"]) == (201, 200, True)


async def test_an_existing_administrator_is_matched_by_email_in_any_case_and_keeps_the_password() -> None:
    harness, google = google_harness(administrators=("OWNER@example.COM",))

    async with app_of(harness) as app, client_at(app) as client:
        response = await signed_in_with_google(client, google, "owner@EXAMPLE.com")
        me = (await client.get("/v1/auth/me")).json()
        with_password = await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)

    assert outcome_of(response) == ("/", None)
    assert (me["user_id"], me["username"], me["has_password"]) == (ADMINISTRATOR.user_id, ADMINISTRATOR.username, True)
    assert with_password.status_code == 200 and len(harness.users.by_id) == 1


async def test_a_user_with_an_administrator_email_is_promoted_and_loses_the_password_nobody_verified() -> None:
    harness, google = google_harness(administrators=(MEMBER.email,))
    harness.users.add(MEMBER, MEMBER_PASSWORD)

    async with app_of(harness) as app, client_at(app) as registered, client_at(app) as client:
        earlier = await sign_in(registered, MEMBER.username, MEMBER_PASSWORD)
        response = await signed_in_with_google(client, google, MEMBER.email)
        me = (await client.get("/v1/auth/me")).json()
        earlier_session = await registered.get("/v1/auth/me")
        with_password = await sign_in(registered, MEMBER.username, MEMBER_PASSWORD)

    assert (earlier.status_code, outcome_of(response)) == (200, ("/", None))
    assert (me["user_id"], me["role"], me["has_password"]) == (MEMBER.user_id, "administrator", False)
    assert (earlier_session.status_code, with_password.status_code) == (401, 401)


async def test_an_allowed_email_signs_in_as_a_user_created_at_the_first_sign_in() -> None:
    harness, google = google_harness(allowed=("friend@example.com",))

    async with app_of(harness) as app, client_at(app) as client:
        first = await signed_in_with_google(client, google, "Friend@Example.com")
        me = (await client.get("/v1/auth/me")).json()
        await client.post("/v1/auth/sign-out")
        again = await signed_in_with_google(client, google, "friend@example.com")
        me_again = (await client.get("/v1/auth/me")).json()
        users = (await client.get("/v1/admin/users")).status_code

    assert (outcome_of(first), outcome_of(again)) == (("/", None), ("/", None))
    assert (me["role"], me["permissions"], me["username"], me["has_password"]) == ("user", [], "Friend", False)
    assert me_again["user_id"] == me["user_id"] and len(harness.users.by_id) == 2 and users == 403


async def test_a_created_username_someone_took_gets_a_suffix() -> None:
    harness, google = google_harness(allowed=("owner@other.example",))

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in_with_google(client, google, "owner@other.example")
        me = (await client.get("/v1/auth/me")).json()

    assert me["username"] == f"owner-{me['user_id'][:8]}"


async def test_any_other_email_is_refused_and_creates_nothing_while_registration_is_closed() -> None:
    harness, google = google_harness(allowed=("friend@example.com",))

    async with app_of(harness) as app, client_at(app) as client:
        stranger = await signed_in_with_google(client, google, "stranger@example.com")
        near = await signed_in_with_google(client, google, "friend@example.com.evil.example")
        me = await client.get("/v1/auth/me")

    assert (outcome_of(stranger), outcome_of(near)) == (("/sign-in", "not_allowed"), ("/sign-in", "not_allowed"))
    assert me.status_code == 401 and list(harness.users.by_id) == [ADMINISTRATOR.user_id]
    assert not any(header.startswith("stock_agent_session=") for header in stranger.headers.get_list("set-cookie"))
    assert "stranger" not in said(harness)


async def test_any_other_email_signs_in_as_a_user_while_registration_is_open_but_never_first() -> None:
    harness, google = google_harness(registration_open=True)

    async with app_of(harness) as app, client_at(app) as client:
        response = await signed_in_with_google(client, google, "anyone@example.com")
        me = (await client.get("/v1/auth/me")).json()

    empty, empty_google = google_harness(registration_open=True, allowed=("friend@example.com",))
    empty.users.by_id.clear()

    async with app_of(empty) as app, client_at(app) as client:
        first = await signed_in_with_google(client, empty_google, "friend@example.com")
        status = (await client.get("/v1/auth/status")).json()

    assert (outcome_of(response), me["role"]) == (("/", None), "user")
    assert outcome_of(first) == ("/sign-in", "not_allowed") and status["needs_first_administrator"] is True


async def test_a_deactivated_account_stays_refused_whatever_list_names_it() -> None:
    harness, google = google_harness(administrators=(OWNER_EMAIL, MEMBER.email))
    harness.users.add(User(**{**vars(MEMBER), "status": UserStatus.DEACTIVATED}), MEMBER_PASSWORD)

    async with app_of(harness) as app, client_at(app) as client:
        response = await signed_in_with_google(client, google, MEMBER.email)
        me = await client.get("/v1/auth/me")

    assert outcome_of(response) == ("/sign-in", "deactivated") and me.status_code == 401
    assert harness.users.by_id[MEMBER.user_id].role == Role.USER


async def test_a_return_with_another_state_or_without_the_flow_cookie_is_refused_before_google_is_asked() -> None:
    harness, google = google_harness()

    async with app_of(harness) as app, client_at(app) as client, client_at(app) as other_browser:
        callback = google.approve(await started(client), OWNER_EMAIL)
        code = parse_qs(urlsplit(callback).query)["code"][0]
        wrong_state = await client.get("/v1/auth/google/callback", params={"state": "another-state", "code": code})
        no_cookie = await returned(other_browser, google.approve(await started(client), OWNER_EMAIL))
        me = await client.get("/v1/auth/me")

    assert outcome_of(wrong_state) == ("/sign-in", "state_mismatch") and outcome_of(no_cookie) == ("/sign-in", "flow_missing")
    assert google.token_requests == 0 and me.status_code == 401
    assert 'stock_agent_google_flow=""' in wrong_state.headers["set-cookie"]


async def test_a_return_is_good_once_and_a_replayed_code_is_refused_by_google_too() -> None:
    harness, google = google_harness()

    async with app_of(harness) as app, client_at(app) as client, client_at(app) as thief:
        callback = google.approve(await started(client), OWNER_EMAIL)
        flow_cookie = client.cookies["stock_agent_google_flow"]
        first = await returned(client, callback)
        replayed = await returned(client, callback)
        thief.cookies.set("stock_agent_google_flow", flow_cookie, domain="127.0.0.1", path="/v1/auth/google")
        with_the_cookie = await returned(thief, callback)
        thief_me = await thief.get("/v1/auth/me")

    assert outcome_of(first) == ("/", None)
    assert outcome_of(replayed) == ("/sign-in", "flow_missing") and outcome_of(with_the_cookie) == ("/sign-in", "provider_failed")
    assert thief_me.status_code == 401


async def test_an_expired_flow_is_refused() -> None:
    harness, google = google_harness()

    async with app_of(harness) as app, client_at(app) as client:
        callback = google.approve(await started(client), OWNER_EMAIL)
        flow_cookie = client.cookies["stock_agent_google_flow"]
        harness.clock.current_time += timedelta(minutes=11)
        client.cookies.set("stock_agent_google_flow", flow_cookie, domain="127.0.0.1", path="/v1/auth/google")
        response = await returned(client, callback)

    assert outcome_of(response) == ("/sign-in", "flow_missing")


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ({"nonce": "another-nonce"}, "token_refused"),
        ({"audience": "another-client.apps.example"}, "token_refused"),
        ({"audience": [CLIENT_ID, "another-client.apps.example"]}, "token_refused"),
        ({"issuer": "https://accounts.evil.example"}, "token_refused"),
        ({"lifetime": timedelta(minutes=-5)}, "token_refused"),
        ({"email_verified": False}, "email_unverified"),
        ({"client_secret": "another-secret"}, "provider_failed"),
    ],
)
async def test_an_id_token_that_is_not_this_sign_ins_own_is_refused(change: dict[str, Any], refusal: str) -> None:
    harness, google = google_harness()
    harness.users.by_id.clear()

    for name, value in change.items():
        setattr(google, name, value)

    async with app_of(harness) as app, client_at(app) as client:
        response = await signed_in_with_google(client, google, OWNER_EMAIL)
        me = await client.get("/v1/auth/me")

    assert outcome_of(response) == ("/sign-in", refusal)
    assert me.status_code == 401 and harness.users.by_id == {}


async def test_a_cancelled_sign_in_and_a_google_that_does_not_answer_end_on_the_sign_in_page() -> None:
    harness, google = google_harness()

    async with app_of(harness) as app, client_at(app) as client:
        address = await started(client)
        state = parse_qs(urlsplit(address).query)["state"][0]
        cancelled = await client.get("/v1/auth/google/callback", params={"state": state, "error": "access_denied"})
        google.down = True
        down = await signed_in_with_google(client, google, OWNER_EMAIL)

    assert (outcome_of(cancelled), outcome_of(down)) == (("/sign-in", "cancelled"), ("/sign-in", "provider_failed"))


async def test_starts_and_failed_returns_count_toward_the_limit_per_address_and_a_sign_in_takes_its_own_back() -> None:
    harness, google = google_harness()
    limit = harness.config.accounts.sign_in_failures_per_client

    async with app_of(harness) as app, client_at(app) as client, client_at(app, "203.0.113.9") as elsewhere:
        for _ in range(limit + 2):
            assert outcome_of(await signed_in_with_google(client, google, OWNER_EMAIL)) == ("/", None)

        failures = [await client.get("/v1/auth/google/callback", params={"state": "x", "code": "y"}) for _ in range(limit + 1)]
        start = await client.get(START)
        from_elsewhere = await signed_in_with_google(elsewhere, google, OWNER_EMAIL)

    assert [outcome_of(failure)[1] for failure in failures] == ["flow_missing"] * limit + ["throttled"]
    assert outcome_of(start) == ("/sign-in", "throttled") and outcome_of(from_elsewhere) == ("/", None)


async def test_nothing_secret_reaches_a_log_or_an_answer() -> None:
    harness, google = google_harness(allowed=("friend@example.com",))
    answers = []

    async with app_of(harness) as app, client_at(app) as client:
        for email, change in (
            ("friend@example.com", {}),
            ("stranger@example.com", {}),
            (OWNER_EMAIL, {"nonce": "bad"}),
            (OWNER_EMAIL, {}),
        ):
            google.nonce = change.get("nonce")
            address = await started(client)
            flow_cookie = client.cookies["stock_agent_google_flow"]
            callback = google.approve(address, email)
            answers.append(
                (await returned(client, callback), parse_qs(urlsplit(callback).query), parse_qs(urlsplit(address).query), flow_cookie)
            )

        replay = await client.get("/v1/auth/google/callback", params={"state": "s", "code": "a-replayed-code-value"})
        status = await client.get("/v1/auth/status")

    everything = said(harness) + status.text + replay.text + str(replay.headers)

    for response, sent_back, asked, flow_cookie in answers:
        everything += response.text + str(response.headers).replace(flow_cookie, "")
        secrets_of_the_flow = [sent_back["code"][0], asked["state"][0], asked["nonce"][0], flow_cookie]
        assert not [secret for secret in secrets_of_the_flow if secret in said(harness)]

    assert CLIENT_SECRET not in everything and "a-replayed-code-value" not in everything and "unsigned" not in everything
    assert "@" not in said(harness) and CLIENT_ID not in status.text
    assert any("refused" in message for _, message in harness.logger.records)


async def test_the_access_log_keeps_the_path_of_a_google_endpoint_and_drops_its_query(caplog: pytest.LogCaptureFixture) -> None:
    harness, _ = google_harness()
    access = logging.getLogger("uvicorn.access")
    line = '%s - "%s %s HTTP/%s" %d'

    async with app_of(harness):
        with caplog.at_level(logging.INFO, logger="uvicorn.access"):
            access.info(line, "203.0.113.9:1", "GET", "/v1/auth/google/callback?state=a-state&code=a-code", "1.1", 303)
            access.info(line, "203.0.113.9:1", "GET", "/v1/auth/google/start?confirmation=an-id", "1.1", 303)
            access.info(line, "203.0.113.9:1", "GET", "/v1/market/stocks?query=2330", "1.1", 200)

    assert [record.getMessage().split('"')[1] for record in caplog.records] == [
        "GET /v1/auth/google/callback HTTP/1.1",
        "GET /v1/auth/google/start HTTP/1.1",
        "GET /v1/market/stocks?query=2330 HTTP/1.1",
    ]


async def test_the_access_log_leaves_out_an_answered_status_check_and_keeps_a_failed_one(caplog: pytest.LogCaptureFixture) -> None:
    harness, _ = google_harness()
    access = logging.getLogger("uvicorn.access")
    line = '%s - "%s %s HTTP/%s" %d'

    async with app_of(harness):
        with caplog.at_level(logging.INFO, logger="uvicorn.access"):
            access.info(line, "127.0.0.1:49154", "GET", "/v1/auth/status", "1.1", 200)
            access.info(line, "100.64.0.9:1", "GET", "/v1/auth/status", "1.1", 200)
            access.info(line, "127.0.0.1:49155", "GET", "/v1/auth/status", "1.1", 500)
            access.info(line, "100.64.0.9:1", "GET", "/v1/auth/me", "1.1", 200)

    assert [record.getMessage().split(" - ")[1] for record in caplog.records] == [
        '"GET /v1/auth/status HTTP/1.1" 500',
        '"GET /v1/auth/me HTTP/1.1" 200',
    ]


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of config/ that offers sign-in with Google at the test's origin, with the keys startup needs in the environment."""
    shutil.copytree(REPOSITORY_CONFIG, tmp_path / "config")
    settings = tmp_path / "config" / "appsetting.yaml"
    text = settings.read_text(encoding="utf-8")
    text = text.replace('public_origin: ""', f'public_origin: "{ORIGIN}"').replace(
        "google_administrator_emails: []", f'google_administrator_emails: ["{OWNER_EMAIL}"]'
    )
    settings.write_text(text, encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ACCOUNTS_KEY", "A" * 43)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", CLIENT_SECRET)
    return tmp_path


def google_only_administrator(project: Path) -> tuple[CliHarness, FakeGoogle]:
    harness, google = google_harness(settings_root=project)
    harness.users.by_id.clear()
    harness.users.add(User(**{**vars(ADMINISTRATOR), "email": OWNER_EMAIL}), None)
    return harness, google


async def save(client: httpx.AsyncClient, **confirmation: str) -> httpx.Response:
    body = {"confirm": True, "changes": [{"path": "ai.temperature", "value": 0.3}], **confirmation}
    return await client.put("/v1/admin/settings", json=body)


async def confirmed(
    client: httpx.AsyncClient, google: FakeGoogle, email: str = OWNER_EMAIL, confirmation: str = CONFIRMATION
) -> httpx.Response:
    address = await started(client, confirmation=confirmation)
    query = parse_qs(urlsplit(address).query)
    assert query["max_age"] == ["0"] and "auth_time" in query["claims"][0]
    return await returned(client, google.approve(address, email))


async def test_an_administrator_without_a_password_confirms_one_save_by_a_fresh_google_authentication(project: Path) -> None:
    harness, google = google_only_administrator(project)

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in_with_google(client, google, OWNER_EMAIL)
        unconfirmed = await save(client)
        with_a_password = await save(client, password="any password at all")
        made_up = await save(client, google_confirmation=CONFIRMATION)
        back = await confirmed(client, google)
        another_save = await save(client, google_confirmation="another-confirmation-id")
        saved = await save(client, google_confirmation=CONFIRMATION)
        again = await client.put(
            "/v1/admin/settings",
            json={"confirm": True, "changes": [{"path": "ai.temperature", "value": 0.4}], "google_confirmation": CONFIRMATION},
        )

    assert [answer.json()["code"] for answer in (unconfirmed, made_up, another_save, again)] == ["google_confirmation_required"] * 4
    assert (with_a_password.status_code, with_a_password.json()["code"]) == (403, "password_refused")
    assert outcome_of(back) == ("/admin/settings", "confirmed")
    assert saved.status_code == 200, saved.text
    assert "temperature: 0.3" in (project / "config" / "appsetting.yaml").read_text(encoding="utf-8")


async def test_a_stale_or_undated_google_authentication_confirms_nothing(project: Path) -> None:
    harness, google = google_only_administrator(project)
    fresh_for = timedelta(
        seconds=harness.config.accounts.google_fresh_authentication_seconds + harness.config.accounts.google_clock_skew_seconds
    )

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in_with_google(client, google, OWNER_EMAIL)
        google.authenticated_ago = fresh_for + timedelta(seconds=1)
        stale = await confirmed(client, google)
        after_stale = await save(client, google_confirmation=CONFIRMATION)
        google.authenticated_ago = None
        undated = await confirmed(client, google)
        after_undated = await save(client, google_confirmation=CONFIRMATION)
        google.authenticated_ago = fresh_for
        fresh = await confirmed(client, google)
        harness.clock.current_time += timedelta(seconds=harness.config.accounts.google_fresh_authentication_seconds + 1)
        too_late = await save(client, google_confirmation=CONFIRMATION)

    assert (outcome_of(stale), outcome_of(undated)) == (("/admin/settings", "stale_authentication"),) * 2
    assert outcome_of(fresh) == ("/admin/settings", "confirmed")
    assert [answer.json()["code"] for answer in (after_stale, after_undated, too_late)] == ["google_confirmation_required"] * 3


async def test_another_google_account_or_another_administrator_confirms_nothing_for_this_one(project: Path) -> None:
    harness, google = google_only_administrator(project)
    second = User(
        user_id=UserId("u-second"),
        username="second",
        email="second@example.com",
        role=Role.ADMINISTRATOR,
        created_at=ADMINISTRATOR.created_at,
    )
    harness.users.add(second, None)
    harness.users.add(MEMBER, MEMBER_PASSWORD)

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in_with_google(client, google, OWNER_EMAIL)
        by_a_user = await confirmed(client, google, MEMBER.email)
        by_a_stranger = await confirmed(client, google, "stranger@example.com")
        by_another_administrator = await confirmed(client, google, second.email)
        refused = await save(client, google_confirmation=CONFIRMATION)

    answers = (by_a_user, by_a_stranger, by_another_administrator)
    assert [outcome_of(answer) for answer in answers] == [("/admin/settings", "not_administrator")] * 3
    assert refused.json()["code"] == "google_confirmation_required"
    assert "temperature: 0.3" not in (project / "config" / "appsetting.yaml").read_text(encoding="utf-8")


async def test_a_confirmation_starts_from_an_administrators_session_and_confirms_that_sessions_save_alone(project: Path) -> None:
    harness, google = google_only_administrator(project)
    harness.users.add(MEMBER, MEMBER_PASSWORD)

    async with app_of(harness) as app, client_at(app) as visitor, client_at(app) as member, client_at(app) as other:
        await sign_in(member, MEMBER.username, MEMBER_PASSWORD)
        refused = [await client.get(START, params={"confirmation": CONFIRMATION}) for client in (visitor, member)]

        async with client_at(app) as administrator:
            await signed_in_with_google(administrator, google, OWNER_EMAIL)
            await signed_in_with_google(other, google, OWNER_EMAIL)
            back = await confirmed(administrator, google)
            from_another_session = await save(other, google_confirmation=CONFIRMATION)
            saved = await save(administrator, google_confirmation=CONFIRMATION)

    assert [outcome_of(answer) for answer in refused] == [("/admin/settings", "not_administrator")] * 2
    assert outcome_of(back) == ("/admin/settings", "confirmed")
    assert (from_another_session.status_code, from_another_session.json()["code"]) == (403, "google_confirmation_required")
    assert saved.status_code == 200, saved.text


async def test_an_administrator_with_a_password_still_confirms_by_the_password_alone(project: Path) -> None:
    harness, google = google_harness(settings_root=project, administrators=(ADMINISTRATOR.email,))

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in_with_google(client, google, ADMINISTRATOR.email)
        await confirmed(client, google, ADMINISTRATOR.email)
        by_google = await save(client, google_confirmation=CONFIRMATION)
        by_password = await save(client, password=ADMINISTRATOR_PASSWORD)

    assert (by_google.status_code, by_google.json()["code"], by_password.status_code) == (403, "password_required", 200)


async def test_a_save_that_would_lock_out_an_administrator_without_a_password_is_refused(project: Path) -> None:
    harness, google = google_only_administrator(project)

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in_with_google(client, google, OWNER_EMAIL)
        await confirmed(client, google)
        refused = await client.put(
            "/v1/admin/settings",
            json={
                "confirm": True,
                "changes": [{"path": "accounts.google_administrator_emails", "value": ["someone.else@example.com"]}],
                "google_confirmation": CONFIRMATION,
            },
        )

    assert refused.status_code == 422 and "no password" in refused.text
    assert OWNER_EMAIL in (project / "config" / "appsetting.yaml").read_text(encoding="utf-8")


async def test_a_password_set_on_the_server_lets_a_google_only_administrator_use_the_password_sign_in() -> None:
    harness, google = google_harness()
    harness.users.by_id.clear()

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in_with_google(client, google, OWNER_EMAIL)
        before = await sign_in(client, "Owner.Gmail", "a password set on the server")
        reset = await harness.runtime.signed_out.reset_password("Owner.Gmail", SecretStr("a password set on the server"))
        after = await sign_in(client, OWNER_EMAIL, "a password set on the server")
        cli = await harness.runtime.signed_out.sign_in("Owner.Gmail", SecretStr("a password set on the server"), "cli")

    assert (before.status_code, after.status_code) == (401, 200)
    assert reset is not None and reset.has_password and after.json()["has_password"] is True and cli.role == Role.ADMINISTRATOR


@pytest.mark.parametrize(
    ("environment", "settings", "names"),
    [
        ({"GOOGLE_CLIENT_ID": CLIENT_ID}, {}, "GOOGLE_CLIENT_SECRET"),
        (
            {"GOOGLE_CLIENT_ID": CLIENT_ID, "GOOGLE_CLIENT_SECRET": CLIENT_SECRET},
            {},
            "accounts.public_origin in config/appsetting.yaml",
        ),
        ({}, {'public_origin: ""': 'public_origin: "https://stock.example.ts.net"'}, "GOOGLE_CLIENT_ID"),
        (
            {"GOOGLE_CLIENT_ID": CLIENT_ID, "GOOGLE_CLIENT_SECRET": CLIENT_SECRET},
            {'public_origin: ""': 'public_origin: "http://stock.example.ts.net"'},
            "must be an https address",
        ),
        (
            {"GOOGLE_CLIENT_ID": CLIENT_ID, "GOOGLE_CLIENT_SECRET": CLIENT_SECRET},
            {'public_origin: ""': 'public_origin: "https://stock.example.ts.net"'},
            "Add stock.example.ts.net to api.allowed_hosts",
        ),
        (
            {"GOOGLE_CLIENT_ID": CLIENT_ID, "GOOGLE_CLIENT_SECRET": CLIENT_SECRET},
            {
                'public_origin: ""': f'public_origin: "{ORIGIN}"',
                "https://oauth2.googleapis.com/token": "http://oauth2.googleapis.com/token",
            },
            "accounts.google_token_endpoint",
        ),
    ],
)
async def test_startup_refuses_a_half_set_up_or_unsafe_google_sign_in_and_names_the_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, environment: dict[str, str], settings: dict[str, str], names: str
) -> None:
    shutil.copytree(REPOSITORY_CONFIG, tmp_path / "config")
    path = tmp_path / "config" / "appsetting.yaml"
    text = path.read_text(encoding="utf-8")

    for old, new in settings.items():
        assert old in text
        text = text.replace(old, new)

    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ACCOUNTS_KEY", "A" * 43)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(InvalidSettingsError) as refused:
        startup_settings(tmp_path, unsettled=0)

    assert names in str(refused.value) and CLIENT_SECRET not in str(refused.value)


async def test_the_settings_form_never_shows_the_client_id_or_the_secret(project: Path) -> None:
    harness, _ = google_harness(settings_root=project, administrators=(ADMINISTRATOR.email,))

    async with app_of(harness) as app, client_at(app) as client:
        await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)
        form = await client.get("/v1/admin/settings")
        written = await client.put(
            "/v1/admin/settings",
            json={
                "confirm": True,
                "changes": [{"path": "accounts.google_client_secret", "value": "x"}],
                "password": ADMINISTRATOR_PASSWORD,
            },
        )

    paths = [field["path"] for field in form.json()]
    assert "accounts.google_administrator_emails" in paths and "accounts.public_origin" not in paths
    assert not [path for path in paths if "google_client" in path] and CLIENT_SECRET not in form.text and CLIENT_ID not in form.text
    assert written.status_code == 422


async def test_a_file_without_googles_addresses_starts_and_offers_no_sign_in_with_google(project: Path) -> None:
    settings = project / "config" / "appsetting.yaml"
    lines = settings.read_text(encoding="utf-8").splitlines(keepends=True)
    addresses = ("  google_issuer:", "  google_authorization_endpoint:", "  google_token_endpoint:")
    settings.write_text("".join(line for line in lines if not line.startswith(addresses)), encoding="utf-8")
    config = startup_settings(project, unsettled=0)
    harness = build_harness(config=config)

    async with app_of(harness) as app, client_at(app) as client:
        offered = (await client.get("/v1/auth/status")).json()["google_sign_in"]
        start = await client.get("/v1/auth/google/start")

    assert (config.accounts.public_origin, config.accounts.google_client_id) == (ORIGIN, CLIENT_ID)
    assert not config.accounts.google_sign_in and offered is False
    assert (start.status_code, start.headers["location"]) == (303, "/sign-in?google=not_offered")
