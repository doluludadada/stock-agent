"""
User accounts over the Web API, as the web app sees them: the first-time setup, registration, sign-in and its limits,
sessions that end, the administrator's users page, and every user's data kept apart.
"""

from dataclasses import replace

import httpx
import pytest
from support.harness import (
    ADMINISTRATOR,
    ADMINISTRATOR_PASSWORD,
    MEMBER,
    MEMBER_PASSWORD,
    CliHarness,
    build_harness,
    harness_config,
    open_harness_switch,
    real_broker_config,
    rising_history,
)
from support.web import app_of, client_at, ended, hold_stock_list, run_to_end, serve, sign_in, write

from a_domain.types.ids import UserId
from d_presentation.web.app import create_app
from d_presentation.web.session import current_user, require_private_access

pytestmark = pytest.mark.asyncio

NEW_USER = {"username": "carol", "email": "Carol@Example.com", "password": "carol's long password"}


def with_member() -> CliHarness:
    harness = build_harness()
    harness.users.add(MEMBER, MEMBER_PASSWORD)
    return harness


async def test_the_first_time_setup_needs_the_code_the_server_printed(capsys: pytest.CaptureFixture[str]) -> None:
    harness = build_harness()
    harness.users.by_id.clear()
    setup = {"username": "hsiu", "email": "hsiu@example.com", "password": "a long first password"}

    async with app_of(harness) as app, client_at(app) as client:
        before = (await client.get("/v1/auth/status")).json()
        code = capsys.readouterr().err.split("setup code ")[1].split(",")[0]
        refused = await client.post("/v1/auth/setup", json={**setup, "setup_code": "wrong"})
        registration = await client.post("/v1/auth/register", json=NEW_USER)
        created = await client.post("/v1/auth/setup", json={**setup, "setup_code": code})
        again = await client.post("/v1/auth/setup", json={**setup, "username": "other", "email": "o@example.com", "setup_code": code})
        after = (await client.get("/v1/auth/status")).json()

    assert before == {"needs_first_administrator": True, "registration_open": False}
    assert (refused.status_code, registration.status_code, created.status_code, again.status_code) == (403, 403, 201, 409)
    assert created.json()["role"] == "administrator" and created.json()["user_id"] == ADMINISTRATOR.user_id
    assert "manage_users" in created.json()["permissions"]
    assert after == {"needs_first_administrator": False, "registration_open": True}


async def test_a_registered_user_signs_in_at_once_with_either_name_in_any_case() -> None:
    async with serve(build_harness(), authorized=False) as client:
        registered = await client.post("/v1/auth/register", json=NEW_USER)
        by_name = await sign_in(client, "CAROL", NEW_USER["password"])
        me = (await client.get("/v1/auth/me")).json()
        by_email = await sign_in(client, "carol@example.COM", NEW_USER["password"])

    assert (registered.status_code, by_name.status_code, by_email.status_code) == (201, 200, 200)
    assert (me["username"], me["email"], me["role"], me["permissions"]) == ("carol", "Carol@Example.com", "user", [])


async def test_a_taken_username_or_email_is_refused_whatever_its_case() -> None:
    async with serve(build_harness(), authorized=False) as client:
        await client.post("/v1/auth/register", json=NEW_USER)
        username = await client.post("/v1/auth/register", json={**NEW_USER, "username": "Carol", "email": "x@example.com"})
        email = await client.post("/v1/auth/register", json={**NEW_USER, "username": "dave", "email": "carol@example.com"})

    assert (username.status_code, email.status_code) == (409, 409)
    assert (username.json()["detail"], email.json()["detail"]) == ("That username is taken.", "That email is taken.")


async def test_registration_is_closed_when_switched_off_and_on_a_real_broker() -> None:
    config = harness_config()
    switched_off = build_harness(
        config=config.model_copy(update={"accounts": config.accounts.model_copy(update={"registration_open": False})})
    )
    real_broker = shioaji_harness()

    for harness in (switched_off, real_broker):
        async with serve(harness, authorized=False) as client:
            status = (await client.get("/v1/auth/status")).json()
            refused = await client.post("/v1/auth/register", json=NEW_USER)

        assert (status["registration_open"], refused.status_code) == (False, 403)


def shioaji_harness() -> CliHarness:
    config = real_broker_config()
    harness = build_harness(config=config)
    harness.users.add(MEMBER, MEMBER_PASSWORD)
    return harness


PRIVATE_PAGES = (
    "/v1/watchlist",
    "/v1/runs",
    "/v1/account/history",
    "/v1/technical-settings",
    "/v1/valuation/market",
    "/v1/market/stocks/2330/technical",
)


async def test_on_a_real_broker_a_user_is_signed_in_but_refused_every_private_page() -> None:
    async with serve(shioaji_harness(), user=(MEMBER.username, MEMBER_PASSWORD)) as client:
        me = await client.get("/v1/auth/me")
        refused = {path: (await client.get(path)).status_code for path in PRIVATE_PAGES}
        again = await client.get("/v1/auth/me")

    assert (me.status_code, again.status_code) == (200, 200)
    assert refused == dict.fromkeys(PRIVATE_PAGES, 403)


def test_every_route_of_a_signed_in_user_passes_the_private_gate_but_the_users_own_record() -> None:
    """The gate is a dependency of the route or its router, so a route that forgets it is found here by name."""
    app = create_app(lambda: open_harness_switch(build_harness()))

    assert routes_asking(app, current_user) - routes_asking(app, require_private_access) == {("GET", "/v1/auth/me")}


async def test_wrong_passwords_are_one_answer_and_the_limit_is_per_name_and_client() -> None:
    harness = build_harness()
    limit = harness.config.accounts.sign_in_failures_per_name

    async with app_of(harness) as app, client_at(app, "10.0.0.9") as stranger, client_at(app, "10.0.0.1") as owner:
        unknown = await sign_in(stranger, "nobody", "whatever password")
        failures = [await sign_in(stranger, "owner", "a wrong password") for _ in range(limit)]
        throttled = await sign_in(stranger, "owner", ADMINISTRATOR_PASSWORD)
        from_elsewhere = await sign_in(owner, "owner", ADMINISTRATOR_PASSWORD)

    assert unknown.json() == failures[0].json() == {"detail": "Wrong username, email or password.", "code": "sign_in_refused"}
    assert {response.status_code for response in [unknown, *failures]} == {401}
    assert throttled.status_code == 429
    assert int(throttled.headers["retry-after"]) == harness.config.accounts.sign_in_window_minutes * 60, "by the app's clock"
    assert from_elsewhere.status_code == 200


async def test_a_session_cookie_is_http_only_strict_and_secure_only_over_https() -> None:
    async with app_of(build_harness()) as app, client_at(app) as plain, client_at(app, scheme="https") as tls:
        over_http = (await sign_in(plain, "owner", ADMINISTRATOR_PASSWORD)).headers["set-cookie"].lower()
        over_https = (await sign_in(tls, "owner", ADMINISTRATOR_PASSWORD)).headers["set-cookie"].lower()

    assert all(part in over_http for part in ("httponly", "samesite=strict", "path=/v1")) and "secure" not in over_http
    assert "secure" in over_https


async def test_signing_out_ends_the_session_and_twice_is_fine() -> None:
    async with serve(build_harness()) as client:
        cookie = client.cookies["stock_agent_session"]
        first = await client.post("/v1/auth/sign-out")
        second = await client.post("/v1/auth/sign-out", cookies={"stock_agent_session": cookie})
        replayed = await client.get("/v1/auth/me", cookies={"stock_agent_session": cookie})

    assert (first.status_code, second.status_code, replayed.status_code) == (204, 204, 401)


async def test_a_user_is_refused_the_administration_pages_and_stays_signed_in() -> None:
    async with serve(with_member(), user=(MEMBER.username, MEMBER_PASSWORD)) as client:
        users = await client.get("/v1/admin/users")
        change = await write(client, "PATCH", f"/v1/admin/users/{MEMBER.user_id}", {"role": "administrator"})
        me = await client.get("/v1/auth/me")

    assert (users.status_code, change.status_code, me.status_code) == (403, 403, 200)
    assert me.json()["role"] == "user"


async def test_a_deactivated_user_is_signed_out_at_the_next_request_and_cannot_sign_in() -> None:
    harness = with_member()

    async with app_of(harness) as app, client_at(app) as administrator, client_at(app) as member:
        await sign_in(administrator, "owner", ADMINISTRATOR_PASSWORD)
        await sign_in(member, "member", MEMBER_PASSWORD)
        before = await member.get("/v1/watchlist")
        changed = await write(administrator, "PATCH", f"/v1/admin/users/{MEMBER.user_id}", {"status": "deactivated"})
        after = await member.get("/v1/watchlist")
        again = await sign_in(member, "member", MEMBER_PASSWORD)
        listed = (await administrator.get("/v1/admin/users")).json()

    assert (before.status_code, changed.status_code, after.status_code, again.status_code) == (200, 200, 401, 401)
    assert [(user["username"], user["status"]) for user in listed] == [("owner", "active"), ("member", "deactivated")]


async def test_a_new_password_from_the_administrator_ends_the_users_sessions() -> None:
    harness = with_member()

    async with app_of(harness) as app, client_at(app) as administrator, client_at(app) as member:
        await sign_in(administrator, "owner", ADMINISTRATOR_PASSWORD)
        await sign_in(member, "member", MEMBER_PASSWORD)
        await write(administrator, "PATCH", f"/v1/admin/users/{MEMBER.user_id}", {"password": "a fresh password set"})
        ended_session = await member.get("/v1/auth/me")
        old = await sign_in(member, "member", MEMBER_PASSWORD)
        new = await sign_in(member, "member", "a fresh password set")

    assert (ended_session.status_code, old.status_code, new.status_code) == (401, 401, 200)


async def test_the_last_active_administrator_can_be_neither_demoted_nor_deactivated() -> None:
    async with serve(build_harness()) as client:
        demoted = await write(client, "PATCH", f"/v1/admin/users/{ADMINISTRATOR.user_id}", {"role": "user"})
        deactivated = await write(client, "PATCH", f"/v1/admin/users/{ADMINISTRATOR.user_id}", {"status": "deactivated"})
        missing = await write(client, "PATCH", "/v1/admin/users/nobody", {"role": "user"})
        me = (await client.get("/v1/auth/me")).json()

    assert (demoted.status_code, deactivated.status_code, missing.status_code) == (409, 409, 404)
    assert me["role"] == "administrator"


async def test_another_users_run_is_unknown_and_their_runs_never_block_each_other() -> None:
    harness = with_member()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    release = hold_stock_list(harness)

    async with app_of(harness) as app, client_at(app) as alice, client_at(app) as bob:
        await sign_in(alice, "owner", ADMINISTRATOR_PASSWORD)
        await sign_in(bob, "member", MEMBER_PASSWORD)
        alices = (await write(alice, "POST", "/v1/runs/full-cycle", {})).json()["run_id"]
        bobs = await write(bob, "POST", "/v1/runs/full-cycle", {})
        while_running = [(await bob.get(f"/v1/runs/{alices}{part}")).status_code for part in ("", "/signals", "/orders")]
        release.set()
        await ended(alice, alices)
        await ended(bob, bobs.json()["run_id"])
        after = [(await bob.get(f"/v1/runs/{alices}{part}")).status_code for part in ("", "/signals", "/orders")]
        bobs_runs = [run["run_id"] for run in (await bob.get("/v1/runs")).json()]

    assert bobs.status_code == 202
    assert while_running == after == [404, 404, 404]
    assert bobs_runs == [bobs.json()["run_id"]]
    assert {str(run_id) for run_id in harness.journal.runs} == {alices}
    assert str(next(iter(harness.owners[MEMBER.user_id].journal.runs))) == bobs.json()["run_id"]


async def test_users_run_at_most_the_servers_cap_at_once_and_an_administrator_always_starts() -> None:
    harness = with_member()
    harness.users.add(replace(MEMBER, user_id=UserId("u-carol"), username="carol", email="carol@example.com"), "carol password here")
    harness.config.accounts.max_concurrent_runs = 1
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    release = hold_stock_list(harness)

    async with app_of(harness) as app, client_at(app) as bob, client_at(app) as carol, client_at(app) as alice:
        await sign_in(bob, "member", MEMBER_PASSWORD)
        await sign_in(carol, "carol", "carol password here")
        await sign_in(alice, "owner", ADMINISTRATOR_PASSWORD)
        first = await write(bob, "POST", "/v1/runs/full-cycle", {})
        refused = await write(carol, "POST", "/v1/runs/full-cycle", {})
        administrators = await write(alice, "POST", "/v1/runs/full-cycle", {})
        release.set()
        await ended(bob, first.json()["run_id"])
        await ended(alice, administrators.json()["run_id"])
        later = await run_to_end(carol, "/v1/runs/full-cycle")

    assert (first.status_code, refused.status_code, administrators.status_code, later["state"]) == (202, 429, 202, "finished")


def served_routes(app) -> dict[tuple[str, str], object]:
    """Every /v1 route the app serves, by method and path, with its dependencies, the routers' included."""
    served = [
        context
        for route in app.routes
        for context in (route.effective_route_contexts() if hasattr(route, "effective_route_contexts") else [route])
    ]

    return {
        (method, route.path): route.dependant
        for route in served
        if hasattr(route, "dependant") and route.path.startswith("/v1")
        for method in route.methods
    }


def asks_for(dependant, call: object) -> bool:
    return dependant.call is call or any(asks_for(sub, call) for sub in dependant.dependencies)


def routes_asking(app, call: object) -> set[tuple[str, str]]:
    return {route for route, dependant in served_routes(app).items() if asks_for(dependant, call)}


def public_routes(app) -> set[tuple[str, str]]:
    """
    Every route the app serves whose dependencies, the routers' included, never ask for a session: read from the app,
    so a new public route is listed here without editing this test.
    """
    return set(served_routes(app)) - routes_asking(app, current_user)


PUBLIC_REQUESTS: dict[tuple[str, str], dict[str, object]] = {
    ("GET", "/v1/auth/status"): {},
    ("POST", "/v1/auth/setup"): {
        "json": {"setup_code": "x", "username": "zed", "email": "z@example.com", "password": "a long password"}
    },
    ("POST", "/v1/auth/register"): {"json": NEW_USER},
    ("POST", "/v1/auth/sign-in"): {"json": {"identifier": "owner", "password": ADMINISTRATOR_PASSWORD}},
    ("POST", "/v1/auth/sign-out"): {},
    ("GET", "/v1/market/stocks"): {"params": {"query": "2330"}},
    ("GET", "/v1/market/most-traded"): {},
    ("GET", "/v1/market/breadth"): {},
    ("GET", "/v1/market/indexes/{index}"): {"path": {"index": "taiex"}},
    ("GET", "/v1/market/stocks/{stock_id}"): {"path": {"stock_id": "2330"}},
    ("GET", "/v1/technical-settings/built-in-strategies"): {},
    ("POST", "/v1/webhook/line"): {"json": {"destination": "x", "events": []}},
}
"""A sample request of every route that needs no session."""


async def test_no_public_route_reaches_a_port_that_holds_a_users_data() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))

    async with app_of(harness) as app, client_at(app) as client:
        routes = public_routes(app)
        statuses = {}

        for (method, path), request in PUBLIC_REQUESTS.items():
            url = path.format(**request.get("path", {}))
            response = await client.request(method, url, json=request.get("json"), params=request.get("params"))
            statuses[method, path] = response.status_code

    assert set(routes) == set(PUBLIC_REQUESTS)
    assert {key: code for key, code in statuses.items() if code == 401} == {}


async def test_the_line_webhook_needs_no_session_and_no_app_header() -> None:
    harness = build_harness()

    async with app_of(harness) as app:
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as line:
            response = await line.post("/v1/webhook/line", content=b"{}")

    assert response.status_code in (403, 500)
    assert response.json()["detail"] in ("Invalid signature", "LINE_CHANNEL_SECRET is not set, so LINE calls cannot be verified.")
