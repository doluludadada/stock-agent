import asyncio
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import TypeAdapter
from support.harness import build_harness, falling_history, harness_config, harness_settings, open_harness_switch, rising_history
from support.settings import environment_setup, shipped_config
from support.web import ended, hold_stock_list, run_to_end, serve, write

from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from a_domain.types.enums import ExecutionProvider, OrderMode, SystemEnvironment, TradeAction, WatchlistType
from b_application.config import settings_loader
from b_application.config.settings_loader import InvalidSettingsError
from d_presentation.live_runtime import open_runtime_switch
from d_presentation.web.app import ERROR_ANSWERS, create_app

pytestmark = pytest.mark.asyncio


def settings_document() -> dict[str, Any]:
    """The harness's saved settings as GET /v1/technical-settings answers them: the body a client edits and saves."""
    return TypeAdapter(TechnicalSettings).dump_python(harness_settings(), mode="json")


ORDERING_WRITES = [("POST", "/v1/runs/buzz-scan", {}), ("POST", "/v1/runs/intraday", {})]
VALUATION_WRITES = [("POST", "/v1/valuation/explanation", {"stock_id": "2330", "target_pe": 15})]
"""Read-only, but each request is one paid AI call, so it is confirmed like a write."""
"""The only writes that can lead to an order: Buzz and Intraday, which the API starts on the mock broker only."""

WRITES = [
    ("POST", "/v1/runs/full-cycle", {}),
    ("POST", "/v1/runs/specific-stocks", {"stock_ids": ["2330"]}),
    ("POST", "/v1/watchlist/manual", {"stock_ids": ["2330"]}),
    ("POST", "/v1/watchlist/manual/remove", {"stock_ids": ["2330"]}),
    ("PUT", "/v1/technical-settings", {"settings": settings_document()}),
]


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
    assert [(signal["stock_id"], signal["action"]) for signal in signals] == [("2330", "buy")]
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

    async def broken_settings(initial):
        raise ValueError("stored technical settings of local are not valid")

    harness.technical_settings.load = broken_settings

    async with serve(harness) as client:
        run = await run_to_end(client, "/v1/runs/full-cycle")

    assert (run["state"], run["error"], run["summary"]) == (
        "failed",
        "ValueError: stored technical settings of local are not valid",
        None,
    )
    assert harness.journal.runs == {}


async def test_a_run_that_raised_reads_failed_after_a_restart() -> None:
    harness = build_harness()

    async def unreachable_exchange():
        raise RuntimeError("exchange unreachable")

    harness.stocks.get_all = unreachable_exchange

    async with serve(harness) as client:
        before = await run_to_end(client, "/v1/runs/full-cycle")

    async with serve(harness) as client:
        after = (await client.get(f"/v1/runs/{before['run_id']}")).json()
        [listed] = (await client.get("/v1/runs")).json()

    assert (before["state"], before["error"]) == ("failed", "RuntimeError: exchange unreachable")
    assert (after["state"], after["error"]) == ("failed", "RuntimeError: exchange unreachable")
    assert (listed["state"], listed["error"]) == ("failed", "RuntimeError: exchange unreachable")
    assert after["summary"]["errors"] == ["Run aborted: RuntimeError: exchange unreachable"]


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
    assert record.failure == "CancelledError: "


async def test_a_run_started_elsewhere_reads_from_its_record() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    await harness.run_menu("1")
    [record] = harness.journal.runs.values()
    unfinished = replace(record, run_id=uuid4(), end_time=None)
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


async def test_a_watchlist_add_during_a_listing_outage_answers_503_not_unlisted() -> None:
    harness = build_harness()

    async with serve(harness) as client:
        response = await write(client, "POST", "/v1/watchlist/manual", {"stock_ids": ["2330"]})

    assert (response.status_code, response.json()) == (
        503,
        {"detail": "The TWSE and TPEX listings could not be loaded.", "code": "listing_unavailable"},
    )
    assert harness.watchlist.rows == []


# ----------------------------- Technical settings --------------------------- #

SETTINGS_PATH = "/v1/technical-settings"


@pytest.mark.parametrize("cookie", [None, "forged"], ids=["signed-out", "forged-session"])
async def test_the_saved_settings_are_private_to_the_signed_in_user(cookie: str | None) -> None:
    async with serve(build_harness(), authorized=False) as client:
        response = await client.get(SETTINGS_PATH, cookies={"stock_agent_session": cookie} if cookie else None)

    assert response.status_code == 401
    assert "strategies" not in response.text


async def test_the_saved_settings_come_with_the_revision_a_save_must_carry() -> None:
    async with serve(build_harness()) as client:
        response = await client.get(SETTINGS_PATH)

    assert response.status_code == 200
    assert response.json() == settings_document()
    assert (response.json()["active_strategy_id"], response.json()["revision"]) == ("trend", 0)


async def test_a_save_replaces_the_settings_raises_the_revision_and_drives_the_next_run() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    document = settings_document()
    document["strategies"][0]["rules"][0]["condition"]["operator"] = "lt"

    async with serve(harness) as client:
        before = await run_to_end(client, "/v1/runs/specific-stocks", {"stock_ids": ["2330"]})
        saved = await write(client, "PUT", SETTINGS_PATH, {"settings": document})
        read = await client.get(SETTINGS_PATH)
        after = await run_to_end(client, "/v1/runs/specific-stocks", {"stock_ids": ["2330"]})

    assert (saved.status_code, saved.json()) == (200, document | {"revision": 1})
    assert read.json() == saved.json()
    assert before["reports"][0]["technical_report"]["hard_failures"] == []
    assert after["reports"][0]["technical_report"]["hard_failures"] == ["Price Above MA_5"], (
        "price 100 is not below its 5-day average 98"
    )


async def test_a_save_from_a_stale_revision_answers_409_and_saves_nothing() -> None:
    harness = build_harness()
    first = settings_document() | {"active_strategy_id": "buzz"}
    stale = settings_document() | {"buzz_strategy_id": "trend"}

    async with serve(harness) as client:
        accepted = await write(client, "PUT", SETTINGS_PATH, {"settings": first})
        refused = await write(client, "PUT", SETTINGS_PATH, {"settings": stale})
        read = await client.get(SETTINGS_PATH)

    assert (accepted.status_code, refused.status_code) == (200, 409)
    assert read.json() == first | {"revision": 1}


async def test_invalid_settings_are_refused_at_their_fields_under_body_settings_and_nothing_is_saved() -> None:
    harness = build_harness()
    document = settings_document()
    trend = document["strategies"][0]
    trend["indicators"]["ind_a"]["period"] = 0
    trend["indicators"]["ind_m"] = {"kind": "macd", "fast": 26, "slow": 12, "signal": 9}
    document["strategies"][1]["rules"][0]["condition"]["right"] = "15"

    async with serve(harness) as client:
        response = await write(client, "PUT", SETTINGS_PATH, {"settings": document})

    locations = [error["loc"] for error in response.json()["detail"]]
    strategies = ["body", "settings", "strategies"]
    assert response.status_code == 422
    assert [*strategies, 0, "indicators", "ind_a", "sma", "period"] in locations
    assert [*strategies, 0, "indicators", "ind_m", "macd"] in locations
    assert any(location[:9] == [*strategies, 1, "rules", 0, "condition", "comparison", "right"] for location in locations)
    assert all(location[:2] == ["body", "settings"] for location in locations), locations
    assert harness.technical_settings.saved == harness_settings()


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda document: document.update(active_strategy_id="missing"), id="selects-a-missing-strategy"),
        pytest.param(lambda document: document["strategies"].append(document["strategies"][0]), id="duplicate-strategy-id"),
        pytest.param(
            lambda document: document["strategies"][0]["rules"][0]["condition"]["right"].update(indicator_id="ind_z"),
            id="reads-a-missing-indicator",
        ),
    ],
)
async def test_settings_that_contradict_themselves_are_refused_and_nothing_is_saved(change) -> None:
    harness = build_harness()
    document = settings_document()
    change(document)

    async with serve(harness) as client:
        response = await write(client, "PUT", SETTINGS_PATH, {"settings": document})

    assert response.status_code == 422
    assert [error["loc"][:2] for error in response.json()["detail"]] == [["body", "settings"]]
    assert harness.technical_settings.saved == harness_settings()


async def test_the_built_in_strategies_are_public_in_menu_order() -> None:
    async with serve(build_harness(), authorized=False) as client:
        response = await client.get(f"{SETTINGS_PATH}/built-in-strategies")

    built_ins = shipped_config().technical.built_in_strategies
    assert response.status_code == 200
    assert [strategy["strategy_id"] for strategy in response.json()] == ["conservative", "balanced", "aggressive"]
    assert TypeAdapter(tuple[TechnicalStrategy, ...]).validate_python(response.json()) == built_ins


async def test_the_old_settings_page_and_reset_are_gone() -> None:
    harness = build_harness()

    async with serve(harness) as client:
        page = await client.get("/ui/settings")
        reset = await write(client, "POST", f"{SETTINGS_PATH}/reset", {})

    assert (page.status_code, reset.status_code) == (404, 404)
    assert harness.technical_settings.saved == harness_settings()


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
    assert (tsmc["stock_id"], tsmc["mark_price"], tsmc["market_value"]) == ("2330", 112.0, 112_000.0)
    assert (hon_hai["stock_id"], hon_hai["mark_price"]) == ("2317", 50.0)
    assert history["live_stock_ids"] == ["2330"]
    assert history["current"]["equity"] == harness.broker.cash + 112_000.0 + 50_000.0
    assert (history["equity_curve"], history["as_of"]) == ({}, None)
    assert harness.broker.placed == []


async def test_account_history_names_the_broker_and_order_mode_the_settings_choose() -> None:
    harness = build_harness(config=shioaji_config(OrderMode.DISABLED, SystemEnvironment.TEST))
    harness.list_stock("2330", rising_history(110.0))
    harness.hold("2330", quantity=1000, average_cost=100.0)

    async with serve(harness) as client:
        history = (await client.get("/v1/account/history")).json()

    assert (history["execution_provider"], history["order_mode"]) == ("shioaji", "disabled")


# ---------------------------- Permission and scope -------------------------- #


@pytest.mark.parametrize(("method", "path", "body"), WRITES + ORDERING_WRITES + VALUATION_WRITES)
async def test_writes_need_a_session(method: str, path: str, body: dict[str, Any]) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))

    async with serve(harness, authorized=False) as client:
        response = await write(client, method, path, body)

    assert response.status_code == 401
    assert (harness.journal.runs, harness.watchlist.rows, harness.technical_settings.saved) == ({}, [], harness_settings())


@pytest.mark.parametrize(("method", "path", "body"), WRITES + ORDERING_WRITES + VALUATION_WRITES)
async def test_writes_need_the_web_apps_header_so_another_site_cannot_send_them(method: str, path: str, body: dict[str, Any]) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))

    async with serve(harness) as client:
        response = await client.request(method, path, json={"confirm": True, **body}, headers={"X-Requested-With": ""})
        still_signed_in = await client.get("/v1/watchlist")

    assert (response.status_code, still_signed_in.status_code) == (403, 200)
    assert (harness.journal.runs, harness.watchlist.rows, harness.technical_settings.saved) == ({}, [], harness_settings())


@pytest.mark.parametrize("confirm", [{}, {"confirm": False}, {"confirm": "yes"}])
@pytest.mark.parametrize(("method", "path", "body"), WRITES + ORDERING_WRITES + VALUATION_WRITES)
async def test_writes_need_confirm_true(method: str, path: str, body: dict[str, Any], confirm: dict[str, Any]) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))

    async with serve(harness) as client:
        response = await client.request(method, path, json={**body, **confirm})

    assert response.status_code == 422
    assert ["body", "confirm"] in [error["loc"] for error in response.json()["detail"]]
    assert (harness.journal.runs, harness.watchlist.rows, harness.technical_settings.saved) == ({}, [], harness_settings())


PUBLIC_READS = ("/v1/technical-settings/built-in-strategies",)
PRIVATE_READS = ("/v1/runs", "/v1/watchlist", "/v1/technical-settings", "/v1/account/history")


async def test_only_strategy_definitions_and_market_data_are_public() -> None:
    async with serve(build_harness(), authorized=False) as client:
        public = [(await client.get(path)).status_code for path in PUBLIC_READS]
        anonymous = [(await client.get(path)).status_code for path in PRIVATE_READS]
        forged = [(await client.get(path, cookies={"stock_agent_session": "forged"})).status_code for path in PRIVATE_READS]

    assert public == [200]
    assert anonymous == forged == [401, 401, 401, 401]


async def test_a_run_s_decisions_and_orders_are_private() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)

    async with serve(harness) as client:
        run = await run_to_end(client, "/v1/runs/full-cycle")
        client.cookies.clear()
        anonymous = [(await client.get(f"/v1/runs/{run['run_id']}{part}")).status_code for part in ("", "/signals", "/orders")]

    assert anonymous == [401, 401, 401]


async def test_an_unknown_host_is_refused_before_any_route() -> None:
    async with serve(build_harness()) as client:
        response = await client.get("/v1/technical-settings/built-in-strategies", headers={"Host": "attacker.example"})

    assert (response.status_code, response.json()["detail"]) == (400, "Unknown host.")


async def test_api_answers_are_private_unframable_and_unsniffable() -> None:
    async with serve(build_harness()) as client:
        headers = (await client.get("/v1/technical-settings")).headers

    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


async def test_the_api_writes_only_runs_watchlist_settings_and_settings_files_and_says_which_can_order() -> None:
    app = create_app(lambda: open_harness_switch(build_harness()))
    every_write = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method not in {"get", "head"} and not path.startswith(("/v1/webhook", "/v1/admin"))
    }
    writes = {(method, path) for method, path in every_write if not path.startswith("/v1/auth")}

    assert writes == {(method, path) for method, path, _ in WRITES + ORDERING_WRITES + VALUATION_WRITES}
    assert every_write - writes == {("POST", f"/v1/auth/{step}") for step in ("setup", "register", "sign-in", "sign-out")}
    description = app.openapi()["info"]["description"]
    assert "No endpoint places, cancels or modifies an order by itself" in description
    assert "only while the execution provider is" in description


async def test_no_request_but_buzz_and_intraday_reaches_the_broker() -> None:
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

        for path in ("/v1/runs", "/v1/watchlist", "/v1/technical-settings", "/v1/account/history", "/v1/market/stocks/2330"):
            assert (await client.get(path)).status_code == 200

    assert harness.broker.placed == []

    await harness.run_menu("3")

    assert {(order.stock_id, order.action) for order in harness.broker.placed} == {
        ("2330", TradeAction.BUY),
        ("2317", TradeAction.SELL),
    }


def shioaji_config(order_mode: OrderMode, environment: SystemEnvironment):
    """A setup the CLI accepts with the Shioaji broker: order mode disabled reads a real account without ordering."""
    return environment_setup(harness_config(), environment, ExecutionProvider.SHIOAJI, order_mode)


REAL_BROKER_SETUPS = [
    (OrderMode.DISABLED, SystemEnvironment.TEST),
    (OrderMode.DISABLED, SystemEnvironment.PROD),
    (OrderMode.LIVE, SystemEnvironment.PROD),
]


@pytest.mark.parametrize(("order_mode", "environment"), REAL_BROKER_SETUPS)
@pytest.mark.parametrize(("method", "path", "body"), ORDERING_WRITES)
async def test_buzz_and_intraday_are_refused_unless_the_broker_is_the_mock(
    order_mode: OrderMode, environment: SystemEnvironment, method: str, path: str, body: dict[str, Any]
) -> None:
    harness = build_harness(config=shioaji_config(order_mode, environment))
    harness.list_stock("2317", rising_history(100.0), realtime_price=80.0)
    harness.hold("2317", quantity=1000, average_cost=100.0)

    async with serve(harness) as client:
        response = await write(client, method, path, body)

    assert response.status_code == 403
    assert "mock broker" in response.json()["detail"]
    assert (harness.broker.placed, harness.journal.runs, harness.journal.orders) == ([], {}, {})


async def test_web_intraday_on_the_mock_broker_orders_as_the_cli_does_and_records_first() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", rising_history(100.0), realtime_price=80.0)
    harness.hold("2317", quantity=1000, average_cost=100.0)
    harness.watch("2330", WatchlistType.MANUAL)

    async with serve(harness) as client:
        run = await run_to_end(client, "/v1/runs/intraday")
        orders = (await client.get(f"/v1/runs/{run['run_id']}/orders")).json()
        signals = (await client.get(f"/v1/runs/{run['run_id']}/signals")).json()

    assert (run["state"], run["summary"]["workflow"], run["summary"]["execution_provider"]) == ("finished", "intraday", "mock")
    placed = {(order.stock_id, order.action) for order in harness.broker.placed}
    assert placed == {("2330", TradeAction.BUY), ("2317", TradeAction.SELL)}
    assert {order["decision_id"] for order in orders} <= {signal["decision_id"] for signal in signals}
    assert len(orders) == len({order["stock_id"] for order in orders})
    assert all(order["run_id"] == run["run_id"] for order in orders)


async def test_a_settings_read_that_a_save_interrupts_answers_409_and_the_next_read_succeeds() -> None:
    harness = build_harness()
    harness.technical_settings.interrupted_loads = 1

    async with serve(harness) as client:
        interrupted = await client.get("/v1/technical-settings")
        again = await client.get("/v1/technical-settings")

    assert interrupted.status_code == 409 and "Read them again" in interrupted.json()["detail"]
    assert again.status_code == 200 and again.json()["revision"] == harness_settings().revision


async def test_the_api_refuses_to_start_on_the_trading_setups_the_cli_refuses(monkeypatch) -> None:
    unsafe = shipped_config()
    unsafe.environment = SystemEnvironment.DEV
    unsafe.trading.execution_provider = ExecutionProvider.SHIOAJI
    monkeypatch.setattr(settings_loader, "load_settings", lambda project_root, texts: unsafe)
    app = create_app(open_runtime_switch)

    with pytest.raises(InvalidSettingsError, match="trading.execution_provider: environment dev trades only on mock, not shioaji"):
        async with app.router.lifespan_context(app):
            pass


REFUSED_START = """
import sys
from contextlib import asynccontextmanager

import uvicorn

import main
from c_infrastructure.database.db_connector import OutdatedDatabaseError
from d_presentation.dependencies import TradingSetupError


@asynccontextmanager
async def refuse():
    raise {"outdated": OutdatedDatabaseError, "setup": TradingSetupError}[sys.argv[1]]("Remedy: delete stock_agent.db")
    yield


main.open_runtime_switch = refuse
uvicorn.run(main.app, host="127.0.0.1", port=0)
"""


@pytest.mark.parametrize("refusal", ["outdated", "setup"])
async def test_the_served_api_prints_a_refused_start_alone_and_exits_1(refusal: str) -> None:
    """main.py's app, served by uvicorn as `just run-bn` serves it, prints the refusal as the CLI does: no traceback."""
    backend = Path(__file__).resolve().parents[1]
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        REFUSED_START,
        refusal,
        cwd=backend,
        env={"PYTHONPATH": str(backend / "src"), "PATH": "/usr/bin:/bin"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)

    assert process.returncode == 1
    assert "Remedy: delete stock_agent.db" in stderr.decode()
    assert "Traceback" not in (stdout + stderr).decode()


# ------------------------- Watchlist removal and bounds ------------------------ #


async def test_removing_from_the_manual_watchlist_keeps_automatic_entries() -> None:
    harness = build_harness()
    harness.watch("2330", WatchlistType.MANUAL)
    harness.watch("2330", WatchlistType.TECHNICAL)
    harness.watch("2317", WatchlistType.BUZZ)

    async with serve(harness) as client:
        response = await write(client, "POST", "/v1/watchlist/manual/remove", {"stock_ids": ["2330", "2317"]})

    assert response.json() == {"watchlist_type": "manual", "removed_stock_ids": ["2330"], "absent_stock_ids": ["2317"]}
    assert sorted(harness.watchlist.rows) == [("2317", WatchlistType.BUZZ), ("2330", WatchlistType.TECHNICAL)]


async def test_stock_id_lists_are_deduplicated_and_bounded() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))
    async with serve(harness) as client:
        repeated = await write(client, "POST", "/v1/watchlist/manual", {"stock_ids": ["2330", " 2330 ", "2330"]})
        too_many = await write(client, "POST", "/v1/runs/specific-stocks", {"stock_ids": [f"{2300 + index}" for index in range(21)]})
        malformed = await write(client, "POST", "/v1/watchlist/manual", {"stock_ids": ["2330; DROP TABLE"]})

    assert repeated.json()["added_stock_ids"] == ["2330"]
    assert too_many.status_code == 422 and harness.journal.runs == {} and harness.ai.calls == []
    assert malformed.status_code == 422


async def test_specific_stock_reports_survive_a_server_restart() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)

    async with serve(harness) as client:
        run = await run_to_end(client, "/v1/runs/specific-stocks", {"stock_ids": ["2330"]})

    async with serve(harness) as restarted:
        again = (await restarted.get(f"/v1/runs/{run['run_id']}")).json()

    assert [report["stock_id"] for report in again["reports"]] == ["2330"]
    assert again["reports"] == run["reports"] and again["reports"][0]["ai_report"]["score"] == 90


async def test_runs_page_by_offset_newest_first() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    for _ in range(3):
        await harness.run_menu("1")
        harness.clock.current_time += timedelta(minutes=1)

    async with serve(harness) as client:
        first = (await client.get("/v1/runs", params={"limit": 2})).json()
        second = (await client.get("/v1/runs", params={"limit": 2, "offset": 2})).json()
        too_far = await client.get("/v1/runs", params={"offset": 10_001})

    starts = [run["summary"]["start_time"] for run in first + second]
    assert len(first) == 2 and len(second) == 1 and starts == sorted(starts, reverse=True)
    assert too_far.status_code == 422


async def test_an_oversized_body_is_refused_before_any_route_reads_it() -> None:
    harness = build_harness()

    async with serve(harness, authorized=False) as client:
        huge = await client.put(
            "/v1/technical-settings", content=b"{" + b" " * 2_000_100 + b"}", headers={"Content-Type": "application/json"}
        )

    assert huge.status_code == 413
    assert harness.technical_settings.saved == harness_settings()


async def test_a_formula_nested_too_deep_is_refused_without_saving() -> None:
    harness = build_harness()
    document = settings_document()
    expression: object = 1.0
    for _ in range(400):
        expression = {"type": "arithmetic", "operator": "add", "left": expression, "right": 1.0}
    document["strategies"][0]["rules"][0]["condition"] = {
        "type": "comparison",
        "operator": "gt",
        "left": {"type": "market", "field": "close"},
        "right": expression,
    }

    async with serve(harness) as client:
        response = await client.put("/v1/technical-settings", json={"confirm": True, "settings": document})

    assert response.status_code == 422
    assert harness.technical_settings.saved == harness_settings()


@pytest.mark.parametrize("encoding", ["chunked", "gzip, chunked", "identity"])
async def test_a_body_without_a_plain_length_is_refused(encoding: str) -> None:
    harness = build_harness()

    async with serve(harness, authorized=False) as client:
        response = await client.post("/v1/runs/full-cycle", content=b'{"confirm": true}', headers={"Transfer-Encoding": encoding})

    assert response.status_code == 413
    assert harness.journal.runs == {}


def test_every_refusal_has_its_own_code() -> None:
    codes = [code for _, code in ERROR_ANSWERS.values()]

    assert len(set(codes)) == len(codes)
