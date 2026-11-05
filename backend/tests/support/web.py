import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from d_presentation.web.app import create_app
from support.harness import ADMINISTRATOR, ADMINISTRATOR_PASSWORD, CliHarness, open_harness_switch

APP_REQUEST = {"X-Requested-With": "stock-agent"}
"""The header the web app sends with every write; the API refuses a write without it (CSRF)."""


async def sign_in(client: httpx.AsyncClient, identifier: str, password: str) -> httpx.Response:
    """Signs in as the web app does; the client keeps the session cookie for its next requests."""
    return await client.post("/v1/auth/sign-in", json={"identifier": identifier, "password": password})


@asynccontextmanager
async def app_of(harness: CliHarness):
    """The real app with its lifespan running, for a test that needs clients of several users or addresses."""
    app = create_app(lambda: open_harness_switch(harness))

    async with app.router.lifespan_context(app):
        yield app


def client_at(app, address: str = "127.0.0.1", scheme: str = "http") -> httpx.AsyncClient:
    """A client of the app from `address`, sending the app's header as the web app does."""
    transport = httpx.ASGITransport(app=app, client=(address, 50_000))
    return httpx.AsyncClient(transport=transport, base_url=f"{scheme}://127.0.0.1", headers=APP_REQUEST)


def hold_stock_list(harness: CliHarness) -> asyncio.Event:
    """Makes every workflow wait at its first stock-list call until the returned event is set."""
    release = asyncio.Event()
    get_all, get_by_id = harness.stocks.get_all, harness.stocks.get_by_id

    async def held_get_all():
        await release.wait()
        return await get_all()

    async def held_get_by_id(stock_id: str):
        await release.wait()
        return await get_by_id(stock_id)

    harness.stocks.get_all, harness.stocks.get_by_id = held_get_all, held_get_by_id
    return release


@asynccontextmanager
async def serve(
    harness: CliHarness, *, authorized: bool = True, user: tuple[str, str] | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    """
    The real app over the harness runtime, with its lifespan running, as the web app sees it: every request carries
    the app's X-Requested-With header. An authorized client is signed in as the administrator, or as `user` (a
    sign-in name and password the harness knows); an unauthorized one is signed out.
    """
    app = create_app(lambda: open_harness_switch(harness))

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=APP_REQUEST) as client,
    ):
        if authorized:
            identifier, password = user or (ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)
            signed_in = await sign_in(client, identifier, password)
            assert signed_in.status_code == 200, signed_in.text

        yield client


async def write(client: httpx.AsyncClient, method: str, path: str, body: dict[str, Any]) -> httpx.Response:
    return await client.request(method, path, json={"confirm": True, **body})


async def ended(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    for _ in range(500):
        run = (await client.get(f"/v1/runs/{run_id}")).json()

        if run["state"] != "running":
            return run

        await asyncio.sleep(0.01)

    raise AssertionError(f"run {run_id} is still running")


async def run_to_end(client: httpx.AsyncClient, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    response = await write(client, "POST", path, body or {})
    assert response.status_code == 202, response.text
    return await ended(client, response.json()["run_id"])
