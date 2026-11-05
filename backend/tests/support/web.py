import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from typing import Any

import httpx

from b_application.config.api_config import ApiConfig
from d_presentation.web.app import create_app
from support.harness import CliHarness

TOKEN = "test-token"
ADMIN_TOKEN = "test-admin-token"
AUTHORIZED = {"Authorization": f"Bearer {TOKEN}"}
ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@asynccontextmanager
async def serve(
    harness: CliHarness, token: str | None = TOKEN, *, authorized: bool = True, admin_token: str | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    """
    The real app over the harness runtime, with its lifespan running, as a client sees it. An authorized client
    sends the owner's bearer token with every request.
    """
    harness.config.api = ApiConfig(API_TOKEN=token, ADMIN_API_TOKEN=admin_token)
    app = create_app(lambda: nullcontext(harness.runtime))

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=AUTHORIZED if authorized else {}
        ) as client,
    ):
        yield client


async def write(client: httpx.AsyncClient, method: str, path: str, body: dict[str, Any]) -> httpx.Response:
    return await client.request(method, path, json={"confirm": True, **body}, headers=AUTHORIZED)


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
