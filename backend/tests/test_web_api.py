import ast
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from support.harness import CliHarness, build_harness, falling_history, harness_settings, rising_history

from a_domain.types.enums import ExecutionProvider, SystemEnvironment, TradeAction, WatchlistType
from b_application.config.api_config import ApiConfig
from b_application.config.app_config import AppConfig
from c_infrastructure.technical.technical_settings_schema import TechnicalSettingsSchema
from d_presentation import dependencies
from d_presentation.dependencies import TradingSetupError, open_runtime
from d_presentation.web.app import create_app

pytestmark = pytest.mark.asyncio

TOKEN = "test-token"
AUTHORIZED = {"Authorization": f"Bearer {TOKEN}"}


def settings_document() -> dict[str, Any]:
    return TechnicalSettingsSchema.from_domain(harness_settings()).to_document()


WRITES = [
    ("POST", "/v1/runs/full-cycle", {}),
    ("POST", "/v1/runs/specific-stocks", {"stock_ids": ["2330"]}),
    ("POST", "/v1/watchlist/manual", {"stock_ids": ["2330"]}),
    ("PUT", "/v1/technical-settings", {"settings": settings_document()}),
    ("POST", "/v1/technical-settings/reset", {}),
]


@asynccontextmanager
async def serve(harness: CliHarness, token: str | None = TOKEN) -> AsyncIterator[httpx.AsyncClient]:
    """The real app over the harness runtime, with its lifespan running, as a client sees it."""
    harness.config.api = ApiConfig(API_TOKEN=token)
    app = create_app(lambda: nullcontext(harness.runtime))

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client,
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


# ----------------------------------- Runs ----------------------------------- #


async def test_full_cycle_runs_in_the_background_under_the_run_id_it_returns() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", falling_history(100.0), realtime_price=100.0)

    async with serve(harness) as client:
        run = await run_to_end(client, "/v1/runs/full-cycle")
        signals = (await client.get(f"/v1/runs/{run['run_id']}/signals")).json()
        orders = (await client.get(f"/v1/runs/{run['run_id']}/orders")).json()
        recent = (await client.get("/v1/runs", params={"limit": 5})).json()

    [record] = harness.journal.runs.values()
    assert run["run_id"] == str(record.run_id)
    assert (run["state"], run["error"], run["summary"]["workflow"]) == ("finished", None, "full_cycle")
    assert (run["summary"]["total_scanned"], run["summary"]["passed_technical"], run["summary"]["signals_generated"]) == (2, 1, 1)
    assert [(signal["stock_id"], signal["action"], signal["run_id"]) for signal in signals] == [("2330", "buy", run["run_id"])]
    assert [signal["decision_id"] for signal in signals] == [str(signal.decision_id) for signal in harness.journal.signals]
    assert signals[0]["technical_report"]["score"] == 90 and signals[0]["ai_report"]["score"] == 90
    assert orders == [] and harness.broker.placed == []
    assert [(entry["run_id"], entry["state"]) for entry in recent] == [(run["run_id"], "finished")]


async def test_specific_stock_analysis_reports_each_requested_stock() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.ai.scores["2330"] = 70

    async with serve(harness) as client:
        run = await run_to_end(client, "/v1/runs/specific-stocks", {"stock_ids": ["2330", " 9999 "]})

    [report] = run["reports"]
    assert (run["state"], run["summary"]["workflow"]) == ("finished", "specific_stocks")
    assert (report["stock_id"], report["name"], report["current_price"]) == ("2330", "Stock 2330", 100.0)
    assert (report["technical_report"]["score"], report["ai_report"]["score"], report["ai_report"]["summary"]) == (
        90,
        70,
        "fake analysis of 2330",
    )
    assert report["composite_score"] == 80
    assert "Stock not found: 9999" in run["summary"]["errors"]
    assert (harness.journal.signals, harness.journal.orders, harness.broker.placed) == ([], {}, [])


async def test_one_run_at_a_time_and_the_running_one_reads_as_running() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    release = hold_stock_list(harness)

    async with serve(harness) as client:
        started = await write(client, "POST", "/v1/runs/full-cycle", {})
        run_id = started.json()["run_id"]
        second = await write(client, "POST", "/v1/runs/specific-stocks", {"stock_ids": ["2330"]})
        running = (await client.get(f"/v1/runs/{run_id}")).json()

        release.set()
        finished = await ended(client, run_id)
        after = await write(client, "POST", "/v1/runs/specific-stocks", {"stock_ids": ["2330"]})

    assert started.status_code == 202
    assert second.status_code == 409 and run_id in second.json()["detail"]
    assert (running["state"], running["summary"]["workflow"], running["summary"]["end_time"]) == ("running", "full_cycle", None)
    assert finished["state"] == "finished"
    assert after.status_code == 202


async def test_a_run_stopped_by_unreadable_settings_reports_why_without_a_record() -> None:
    harness = build_harness()

    async def broken_settings():
        raise ValueError("technical.local.yaml: strategies is not a mapping")

    harness.technical_settings.load = broken_settings

    async with serve(harness) as client:
        run = await run_to_end(client, "/v1/runs/full-cycle")

    assert (run["state"], run["error"], run["summary"]) == (
        "failed",
        "ValueError: technical.local.yaml: strategies is not a mapping",
        None,
    )
    assert harness.journal.runs == {}


async def test_shutdown_records_the_running_run_as_aborted() -> None:
    harness = build_harness()
    hold_stock_list(harness)

    async with serve(harness) as client:
        run_id = (await write(client, "POST", "/v1/runs/full-cycle", {})).json()["run_id"]
        await asyncio.sleep(0.01)

    [record] = harness.journal.runs.values()
    assert str(record.run_id) == run_id
    assert record.end_time is not None
    assert [error for error in record.errors if error.startswith("Run aborted: CancelledError")]


async def test_a_run_started_elsewhere_reads_from_its_record() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    await harness.run_menu("1")
    [record] = harness.journal.runs.values()
    unfinished = record.model_copy(update={"run_id": uuid4(), "end_time": None})
    await harness.journal.save_run(unfinished)

    async with serve(harness) as client:
        finished = (await client.get(f"/v1/runs/{record.run_id}")).json()
        open_record = (await client.get(f"/v1/runs/{unfinished.run_id}")).json()

    assert (finished["state"], finished["summary"]["signals_generated"], finished["reports"]) == ("finished", 1, [])
    assert open_record["state"] == "unfinished"


@pytest.mark.parametrize("path", ["/v1/runs/{run_id}", "/v1/runs/{run_id}/signals", "/v1/runs/{run_id}/orders"])
async def test_an_unknown_run_is_not_found(path: str) -> None:
    async with serve(build_harness()) as client:
        response = await client.get(path.format(run_id=uuid4()))

    assert response.status_code == 404


async def test_orders_of_a_run_carry_status_reason_costs_and_ids() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    await harness.run_menu("4", stock_ids="2330", buy={"2330"})
    [order] = harness.journal.orders.values()

    async with serve(harness) as client:
        [shown] = (await client.get(f"/v1/runs/{order.run_id}/orders")).json()

    assert (shown["id"], shown["run_id"], shown["decision_id"]) == (str(order.id), str(order.run_id), str(order.decision_id))
    assert (shown["status"], shown["reason"], shown["fee"], shown["tax"], shown["realized_pnl"]) == (
        order.status.value,
        order.reason,
        order.fee,
        order.tax,
        order.realized_pnl,
    )
    assert shown["filled_quantity"] == order.quantity > 0


# --------------------------------- Watchlist -------------------------------- #


async def test_watchlist_shows_each_entry_with_its_type_and_expiry() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.watch("2317", WatchlistType.MANUAL)
    await harness.run_menu("1")

    async with serve(harness) as client:
        entries = (await client.get("/v1/watchlist")).json()

    technical_expiry = harness.watchlist.entries[("2330", WatchlistType.TECHNICAL)].expires_at
    assert [(entry["stock_id"], entry["watchlist_type"], entry["expires_at"]) for entry in entries] == [
        ("2317", "manual", None),
        ("2330", "technical", technical_expiry.isoformat()),
    ]


async def test_adding_to_the_manual_watchlist_reports_new_and_present_stocks() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))
    harness.list_stock("2317", rising_history(100.0))
    harness.watch("2330", WatchlistType.MANUAL)

    async with serve(harness) as client:
        response = await write(client, "POST", "/v1/watchlist/manual", {"stock_ids": ["2330", "2317"]})

    assert response.status_code == 200
    assert response.json() == {"watchlist_type": "manual", "added_stock_ids": ["2317"], "already_present_stock_ids": ["2330"]}
    assert sorted(harness.watchlist.rows) == [("2317", WatchlistType.MANUAL), ("2330", WatchlistType.MANUAL)]
    assert harness.watchlist.entries[("2317", WatchlistType.MANUAL)].expires_at is None


async def test_an_unlisted_stock_id_adds_nothing_to_the_watchlist() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))

    async with serve(harness) as client:
        response = await write(client, "POST", "/v1/watchlist/manual", {"stock_ids": ["2330", "9999"]})

    assert response.status_code == 422
    assert [(error["loc"], error["msg"]) for error in response.json()["detail"]] == [
        (["body", "stock_ids", 1], "Not a listed stock: 9999")
    ]
    assert harness.watchlist.rows == []


# ----------------------------- Technical settings --------------------------- #


async def test_settings_show_the_active_and_buzz_strategies_and_their_parameters() -> None:
    async with serve(build_harness()) as client:
        document = (await client.get("/v1/technical-settings")).json()
        schema = (await client.get("/v1/technical-settings/schema")).json()

    assert (document["active_strategy_id"], document["buzz_strategy_id"]) == ("trend", "buzz")
    assert document["strategies"]["trend"]["indicators"]["rsi_period"] == 14
    assert set(document["strategies"]["trend"]["indicators"]) == set(schema["$defs"]["IndicatorParametersSchema"]["properties"])


async def test_invalid_settings_are_refused_at_their_fields_and_nothing_is_saved() -> None:
    harness = build_harness()
    document = settings_document()
    document["strategies"]["trend"]["indicators"] |= {"rsi_period": 0, "bb_std": 20}

    async with serve(harness) as client:
        response = await write(client, "PUT", "/v1/technical-settings", {"settings": document})

    indicators = ["body", "settings", "strategies", "trend", "indicators"]
    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [[*indicators, "rsi_period"], [*indicators, "bb_std"]]
    assert await harness.technical_settings.load() == harness_settings()


async def test_saved_settings_drive_the_next_run_and_reset_restores_the_template() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    document = settings_document()
    trend = document["strategies"]["trend"]
    trend["indicators"]["rsi_period"] = 500
    trend["rules"].append({"type": "rsi_range", "effect": "block_on_fail", "min_rsi": 0, "max_rsi": 100})

    async with serve(harness) as client:
        saved = await write(client, "PUT", "/v1/technical-settings", {"settings": document})
        with_saved = await run_to_end(client, "/v1/runs/specific-stocks", {"stock_ids": ["2330"]})
        reset = await write(client, "POST", "/v1/technical-settings/reset", {})
        after_reset = await run_to_end(client, "/v1/runs/specific-stocks", {"stock_ids": ["2330"]})

    assert saved.status_code == 200 and saved.json()["strategies"]["trend"]["indicators"]["rsi_period"] == 500
    assert with_saved["reports"][0]["technical_report"]["hard_failures"] == ["RSI Range 0.0-100.0"]
    assert reset.status_code == 200 and reset.json() == settings_document()
    assert after_reset["reports"][0]["technical_report"]["hard_failures"] == []


async def test_the_settings_page_is_served() -> None:
    async with serve(build_harness()) as client:
        response = await client.get("/ui/settings")

    assert response.status_code == 200 and response.headers["content-type"].startswith("text/html")
    assert "/v1/technical-settings" in response.text


# ---------------------------------- Account --------------------------------- #


async def test_account_history_values_positions_at_their_latest_quote() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(110.0), realtime_price=112.0)
    harness.list_stock("2317", rising_history(50.0))
    harness.hold("2330", quantity=1000, average_cost=100.0)
    harness.hold("2317", quantity=1000, average_cost=40.0)

    async with serve(harness) as client:
        history = (await client.get("/v1/account/history", params={"as_of": "2026-10-19"})).json()

    tsmc, hon_hai = history["current"]["positions"]
    assert (tsmc["position"]["stock_id"], tsmc["mark"]["close"], tsmc["market_value"]) == ("2330", 112.0, 112_000.0)
    assert (hon_hai["position"]["stock_id"], hon_hai["mark"]["close"]) == ("2317", 50.0)
    assert history["live_stock_ids"] == ["2330"]
    assert history["current"]["equity"] == harness.broker.cash + 112_000.0 + 50_000.0
    assert (history["equity_curve"], history["as_of"]) == ([], None)
    assert harness.broker.placed == []


# ---------------------------- Permission and scope -------------------------- #


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
async def test_writes_are_refused_while_api_token_is_unset(method: str, path: str, body: dict[str, Any]) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))

    async with serve(harness, token=None) as client:
        response = await write(client, method, path, body)

    assert response.status_code == 403
    assert (harness.journal.runs, harness.watchlist.rows, await harness.technical_settings.load()) == ({}, [], harness_settings())


@pytest.mark.parametrize("authorization", [None, "Bearer wrong-token", f"Basic {TOKEN}"])
@pytest.mark.parametrize(("method", "path", "body"), WRITES)
async def test_writes_need_the_bearer_token(method: str, path: str, body: dict[str, Any], authorization: str | None) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))
    headers = {"Authorization": authorization} if authorization else {}

    async with serve(harness) as client:
        response = await client.request(method, path, json={"confirm": True, **body}, headers=headers)

    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
    assert (harness.journal.runs, harness.watchlist.rows) == ({}, [])


@pytest.mark.parametrize("confirm", [{}, {"confirm": False}, {"confirm": "yes"}])
@pytest.mark.parametrize(("method", "path", "body"), WRITES)
async def test_writes_need_confirm_true(method: str, path: str, body: dict[str, Any], confirm: dict[str, Any]) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))

    async with serve(harness) as client:
        response = await client.request(method, path, json={**body, **confirm}, headers=AUTHORIZED)

    assert response.status_code == 422
    assert ["body", "confirm"] in [error["loc"] for error in response.json()["detail"]]
    assert (harness.journal.runs, harness.watchlist.rows, await harness.technical_settings.load()) == ({}, [], harness_settings())


async def test_reads_need_no_token() -> None:
    async with serve(build_harness(), token=None) as client:
        statuses = [(await client.get(path)).status_code for path in ("/v1/runs", "/v1/watchlist", "/v1/technical-settings")]

    assert statuses == [200, 200, 200]


async def test_the_api_writes_only_runs_watchlist_and_settings_and_says_it_never_orders() -> None:
    app = create_app(lambda: nullcontext(build_harness().runtime))
    writes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set()) - {"GET", "HEAD"}
        if not route.path.startswith("/v1/webhook")
    }

    assert writes == {(method, path) for method, path, _ in WRITES}
    assert "No endpoint places, cancels or modifies an order." in app.openapi()["info"]["description"]


async def test_no_api_request_reaches_the_broker() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", rising_history(100.0), realtime_price=80.0)
    harness.hold("2317", quantity=1000, average_cost=100.0)

    async with serve(harness) as client:
        for method, path, body in WRITES:
            response = await write(client, method, path, body)
            assert response.status_code in {200, 202}, (path, response.text)

            if response.status_code == 202:
                await ended(client, response.json()["run_id"])

        for path in ("/v1/runs", "/v1/watchlist", "/v1/technical-settings", "/v1/account/history"):
            assert (await client.get(path)).status_code == 200

    assert harness.broker.placed == []

    await harness.run_menu("3")

    assert {(order.stock_id, order.action) for order in harness.broker.placed} == {
        ("2330", TradeAction.BUY),
        ("2317", TradeAction.SELL),
    }


async def test_the_api_refuses_to_start_on_the_trading_setups_the_cli_refuses(monkeypatch) -> None:
    unsafe = AppConfig(project_root=Path("."))
    unsafe.environment = SystemEnvironment.DEV
    unsafe.trading.execution_provider = ExecutionProvider.SHIOAJI
    monkeypatch.setattr(dependencies, "load_settings", lambda: unsafe)
    app = create_app(open_runtime)

    with pytest.raises(TradingSetupError, match="DEV environment requires MockExecutionProvider"):
        async with app.router.lifespan_context(app):
            pass


WEB = Path(__file__).resolve().parents[1] / "src" / "d_presentation" / "web"


async def test_the_api_passes_the_domains_answers_through_and_decides_nothing_itself() -> None:
    modules = {path.relative_to(WEB).as_posix(): ast.parse(path.read_text(encoding="utf-8")) for path in WEB.rglob("*.py")}
    nodes = [(name, node) for name, tree in modules.items() for node in ast.walk(tree)]

    rule_imports = [
        name for name, node in nodes if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("a_domain.rules")
    ]
    settings_read = {
        node.attr
        for _, node in nodes
        if isinstance(node, ast.Attribute) and "config" in {getattr(node.value, "attr", None), getattr(node.value, "id", None)}
    }
    computing_responses = [
        node.name
        for node in ast.walk(modules["schemas.py"])
        if isinstance(node, ast.ClassDef) and any(isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) for item in node.body)
    ]

    assert {"schemas.py", "routers/runs.py", "routers/watchlist.py"} <= set(modules)
    assert rule_imports == [], f"A router or response must not run a domain rule ({rule_imports}): call the use case that does."
    assert settings_read == {"line"}, "Only the LINE webhook reads a setting (its channel secret). Thresholds belong to the domain."
    assert computing_responses == [], f"Responses map domain fields and compute nothing: {computing_responses}"
