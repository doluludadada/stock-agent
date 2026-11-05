"""Menus 5 and 6 over the Web API: read-only, the domain's numbers, AI only on an explicit request."""

import pytest
from support.web import serve, write
from test_valuation_pipeline import market_harness

from a_domain.types.enums import WatchlistType

pytestmark = pytest.mark.asyncio


async def test_valuation_needs_the_owner_token() -> None:
    async with serve(market_harness(), authorized=False) as client:
        statuses = [
            (await client.get(path)).status_code
            for path in ("/v1/valuation/market", "/v1/valuation/scan?target_pe=15&min_undervaluation=0")
        ]

    assert statuses == [401, 401]


async def test_stocks_are_valued_at_the_target_pe_with_eps_semantics_kept() -> None:
    harness = market_harness()
    params = {"stock_ids": ["2330", "1101", "0050", "9999"], "target_pe": 20}

    async with serve(harness) as client:
        answer = (await client.get("/v1/valuation/stocks", params=params)).json()

    reports = {report["valuation"]["stock"]["stock_id"]: report for report in answer["reports"]}
    tsmc, cement = reports["2330"], reports["1101"]
    assert "9999" not in reports
    scenarios = ("conservative", "base", "optimistic")
    assert [tsmc["fair_value"][name]["name"] for name in scenarios] == list(scenarios)
    assert tsmc["fair_value"]["base"]["target_pe"] == 20
    assert tsmc["undervaluation"] == pytest.approx(tsmc["fair_value"]["base"]["undervaluation"])
    assert tsmc["valuation"]["eps"]["kind"] == "trailing_twelve_months"
    assert (cement["fair_value"], cement["valuation"]["current_pe"]) == ("eps_negative", "eps_negative")
    if "0050" in reports:
        assert reports["0050"]["valuation"]["eps"]["reason"] and reports["0050"]["fair_value"] == "eps_unavailable"
    assert tsmc["valuation"]["industry_median_pe"]["sample_size"] >= 1
    assert harness.ai.calls == []


async def test_the_scan_ranks_survivors_and_confirms_them_with_the_strategy_only_when_asked() -> None:
    harness = market_harness()

    async with serve(harness) as client:
        valuation_only = (await client.get("/v1/valuation/scan", params={"target_pe": 100, "min_undervaluation": 0})).json()
        technical = (
            await client.get("/v1/valuation/scan", params={"target_pe": 100, "min_undervaluation": 0, "technical": True})
        ).json()

    assert valuation_only["technical_strategy_id"] is None and valuation_only["survivors"]
    assert technical["technical_strategy_id"] == "trend"
    survivors = {report["valuation"]["stock"]["stock_id"] for report in valuation_only["survivors"]}
    assert set(technical["technical_failures"]) <= survivors
    assert valuation_only["eliminated"]["valuation"]
    assert harness.ai.calls == []


async def test_an_ai_explanation_is_one_explicit_paid_call() -> None:
    harness = market_harness()

    async with serve(harness) as client:
        refused = await client.post("/v1/valuation/explanation", json={"stock_id": "2330", "target_pe": 20})
        explained = await write(client, "POST", "/v1/valuation/explanation", {"stock_id": "2330", "target_pe": 20})

    assert refused.status_code == 422 and len(harness.ai.calls) == 1
    assert explained.status_code == 200 and explained.json()["sections"]


async def test_valuation_endpoints_never_order_record_or_watch() -> None:
    harness = market_harness()
    harness.hold("2330", quantity=1000, average_cost=2000.0)
    harness.watch("2330", WatchlistType.TECHNICAL)

    async with serve(harness) as client:
        await client.get("/v1/valuation/market")
        await client.get("/v1/valuation/stocks", params={"stock_ids": ["2330"], "target_pe": 100})
        await client.get("/v1/valuation/scan", params={"target_pe": 100, "min_undervaluation": 0, "technical": True})
        await write(client, "POST", "/v1/valuation/explanation", {"stock_id": "2330", "target_pe": 100})

    assert harness.broker.placed == []
    assert (harness.journal.runs, harness.journal.signals, harness.journal.orders) == ({}, [], {})
    assert harness.watchlist.rows == [("2330", WatchlistType.TECHNICAL)]
