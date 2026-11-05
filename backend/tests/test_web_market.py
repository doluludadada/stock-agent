from datetime import timedelta

import pytest
from support.harness import HISTORY_LAST_SESSION, build_harness, rising_history
from support.web import serve

from a_domain.model.market.stock import Stock
from a_domain.types.enums import MarketIndex
from d_presentation.web.schemas import public_text

pytestmark = pytest.mark.asyncio


def listed_market():
    harness = build_harness()
    for stock_id, name, volume in (("2330", "台積電", 30_000), ("2303", "聯電", 90_000), ("6230", "超眾", 10)):
        harness.list_stock(stock_id, rising_history(100.0))
        harness.stocks.stocks[stock_id] = Stock(stock_id=stock_id, name=name)
        harness.publish_close(stock_id, 100.0, HISTORY_LAST_SESSION)
        harness.stocks.closes[stock_id] = harness.stocks.closes[stock_id].__class__(
            **{**harness.stocks.closes[stock_id].__dict__, "volume": volume}
        )
    return harness


async def test_search_ranks_the_exact_code_then_code_prefixes_then_names_and_is_public() -> None:
    async with serve(listed_market(), authorized=False) as client:
        by_code = (await client.get("/v1/market/stocks", params={"query": "23"})).json()
        exact = (await client.get("/v1/market/stocks", params={"query": "2330"})).json()
        by_name = (await client.get("/v1/market/stocks", params={"query": "超"})).json()

    assert [stock["stock_id"] for stock in by_code] == ["2330", "2303"]
    assert [stock["stock_id"] for stock in exact] == ["2330"]
    assert exact[0]["today"]["close"] == 100.0
    assert [stock["stock_id"] for stock in by_name] == ["6230"]


@pytest.mark.parametrize(
    "path",
    [
        "/v1/market/stocks?query=2330",
        "/v1/market/most-traded",
        "/v1/market/breadth",
        "/v1/market/stocks/2330",
        "/v1/market/stocks/2330/technical",
    ],
)
async def test_a_listing_read_answers_503_when_the_listing_could_not_be_loaded(path: str) -> None:
    async with serve(build_harness()) as client:
        response = await client.get(path)

    assert response.status_code == 503
    assert response.json() == {"detail": "The TWSE and TPEX listings could not be loaded."}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("query", ["", "x" * 41])
async def test_search_bounds_the_query(query: str) -> None:
    async with serve(listed_market(), authorized=False) as client:
        assert (await client.get("/v1/market/stocks", params={"query": query})).status_code == 422


async def test_most_traded_lists_the_latest_session_by_volume() -> None:
    async with serve(listed_market(), authorized=False) as client:
        stocks = (await client.get("/v1/market/most-traded")).json()

    assert [(stock["stock_id"], stock["today"]["volume"]) for stock in stocks] == [("2303", 90_000), ("2330", 30_000), ("6230", 10)]


async def test_breadth_counts_the_latest_sessions_advancers_and_decliners_overall_and_per_industry() -> None:
    harness = build_harness()
    for stock_id, price, change, industry in (
        ("2330", 101.0, 1.0, "半導體業"),
        ("2303", 49.0, -1.0, "半導體業"),
        ("1101", 28.2, 0.0, "水泥工業"),
        ("0050", 100.6, -3.5, None),
    ):
        harness.list_stock(stock_id, rising_history(price))
        harness.publish_close(stock_id, price, HISTORY_LAST_SESSION, change)
        harness.file_eps(stock_id, {}, industry)

    async with serve(harness, authorized=False) as client:
        breadth = (await client.get("/v1/market/breadth")).json()

    assert breadth["session_close"] == f"{HISTORY_LAST_SESSION.isoformat()}T13:30:00+08:00"
    assert {key: breadth["market"][key] for key in ("advancers", "decliners", "unchanged")} == {
        "advancers": 1,
        "decliners": 2,
        "unchanged": 1,
    }
    # 2330 rose 1 from 100 (+1%) and 2303 fell 1 from 50 (-2%).
    assert breadth["industries"]["半導體業"] == {"advancers": 1, "decliners": 1, "unchanged": 0, "average_change_percent": -0.5}
    assert breadth["industries"]["水泥工業"]["unchanged"] == 1
    assert sorted(breadth["industries"]) == ["半導體業", "水泥工業"]
    assert harness.prices.history_requests == [] and harness.prices.realtime_requests == []


async def test_the_taiex_trend_is_public_and_reads_the_index_history() -> None:
    harness = build_harness()
    harness.prices.index_history[MarketIndex.TAIEX] = rising_history(45_000.0)

    async with serve(harness, authorized=False) as client:
        page = (await client.get("/v1/market/indexes/taiex", params={"bars": 60})).json()
        unknown = await client.get("/v1/market/indexes/tpex")

    assert page["index"] == "taiex"
    assert [bar["close"] for bar in page["bars"]] == [bar.close for bar in rising_history(45_000.0)]
    assert unknown.status_code == 422
    assert harness.prices.realtime_requests == [] and harness.journal.runs == {}


async def test_a_stock_page_reads_the_cached_daily_history_without_a_realtime_quote() -> None:
    harness = listed_market()

    async with serve(harness, authorized=False) as client:
        page = (await client.get("/v1/market/stocks/2330", params={"bars": 60})).json()
        missing = await client.get("/v1/market/stocks/9999")
        invalid = await client.get("/v1/market/stocks/23%2F30")

    assert page["stock"]["name"] == "台積電"
    assert len(page["bars"]) == len(rising_history(100.0)) and page["bars"][-1]["close"] == 100.0
    assert harness.prices.realtime_requests == []
    assert (missing.status_code, invalid.status_code) == (404, 404)
    assert harness.journal.runs == {} and harness.ai.calls == []


async def test_a_stock_pages_latest_bar_carries_the_exchanges_official_change_and_older_bars_none() -> None:
    harness = listed_market()
    harness.publish_close("2330", 100.0, HISTORY_LAST_SESSION, change=-3.5)
    harness.publish_close("2303", 100.0, HISTORY_LAST_SESSION - timedelta(days=1), change=1.0)

    async with serve(harness, authorized=False) as client:
        ex_dividend = (await client.get("/v1/market/stocks/2330")).json()["bars"]
        other_session = (await client.get("/v1/market/stocks/2303")).json()["bars"]

    assert [bar["change"] for bar in ex_dividend[-2:]] == [None, -3.5]
    assert other_session[-1]["change"] is None


async def test_the_technical_evaluation_is_private_and_applies_the_active_strategy() -> None:
    harness = listed_market()

    async with serve(harness, authorized=False) as anonymous:
        refused = await anonymous.get("/v1/market/stocks/2330/technical")

    async with serve(harness) as client:
        result = (await client.get("/v1/market/stocks/2330/technical")).json()

    assert refused.status_code == 401
    assert result["strategy"]["strategy_id"] == "trend"
    assert result["report"]["score"] >= 0 and result["latest_price"] == 100.0
    assert set(result["readings"]) == set(result["strategy"]["indicators"])
    assert all(len(series) == len(result["bar_times"]) for series in result["readings"].values())
    assert harness.prices.realtime_requests == [] and harness.ai.calls == [] and harness.journal.runs == {}


@pytest.mark.parametrize(
    ("message", "hidden"),
    [
        ("Failed: GET https://api.example/v1?api_key=abc123secret&x=1", "abc123secret"),
        ("Authorization: Bearer abcdef123456", "abcdef123456"),
        ("FileNotFoundError: /Users/someone/stock-agent/config/x.yaml missing", "/Users/someone"),
        ("openai said sk-proj-ABCDEFGHIJKLMNOP", "sk-proj-ABCDEFGHIJKLMNOP"),
    ],
)
async def test_server_messages_reach_the_browser_without_credentials_or_paths(message: str, hidden: str) -> None:
    assert hidden not in public_text(message)
