import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from support.settings import shipped_config

from a_domain.types.enums import MarketType
from b_application.config.market_data_config import MarketDataConfig, MarketHoursConfig
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.system.market_clock import TaiwanMarketClock

SOURCES = shipped_config().sources

FIXTURES = Path(__file__).parent / "fixtures"

# Trimmed real responses: STOCK_DAY_ALL as served on 2026-10-30 (session 2026-10-29) and the TPEX close quotes
# for 2026-10-30. 1213 and 1538 (TWSE) and 2035 (TPEX) did not trade in the regular session.
PAYLOADS = {
    SOURCES.exchange.twse_daily_quotes_url: json.loads((FIXTURES / "twse_stock_day_all.json").read_text(encoding="utf-8")),
    SOURCES.exchange.tpex_daily_quotes_url: json.loads(
        (FIXTURES / "tpex_mainboard_daily_close_quotes.json").read_text(encoding="utf-8")
    ),
}


@pytest.fixture
def payloads() -> dict[str, list[dict[str, str]]]:
    return {url: [dict(row) for row in rows] for url, rows in PAYLOADS.items()}


@pytest.fixture
def requests(monkeypatch, payloads: dict[str, list[dict[str, str]]]) -> list[httpx.Request]:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=payloads[str(request.url)])

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))

    return sent


def make_provider() -> TaiwanStockProvider:
    logger = SimpleNamespace(debug=lambda message: None, success=lambda message: None, error=lambda message: None)
    return TaiwanStockProvider(SOURCES.exchange, TaiwanMarketClock(MarketHoursConfig()), MarketDataConfig(), cast(Any, logger))


@pytest.mark.asyncio
async def test_stock_list_keeps_four_digit_codes_from_both_markets(requests: list[httpx.Request]) -> None:
    stocks = await make_provider().get_all()

    assert [(stock.stock_id, stock.name, stock.market) for stock in stocks] == [
        ("1101", "台泥", MarketType.TWSE),
        ("1213", "大飲", MarketType.TWSE),
        ("1538", "正峰", MarketType.TWSE),
        ("2330", "台積電", MarketType.TWSE),
        ("2035", "唐榮", MarketType.TPEX),
        ("6488", "環球晶", MarketType.TPEX),
        ("8069", "元太", MarketType.TPEX),
    ]


@pytest.mark.asyncio
async def test_latest_closes_are_the_official_bars_at_the_session_close(requests: list[httpx.Request]) -> None:
    closes = await make_provider().get_latest_closes()

    assert sorted(closes) == ["1101", "2330", "6488", "8069"]

    tsmc = closes["2330"]
    assert tsmc.ts.isoformat() == "2026-10-29T13:30:00+08:00"
    assert (tsmc.open, tsmc.high, tsmc.low, tsmc.close, tsmc.volume) == (2420.0, 2425.0, 2390.0, 2415.0, 18403916)

    gw = closes["6488"]
    assert gw.ts.isoformat() == "2026-10-30T13:30:00+08:00"
    assert (gw.open, gw.high, gw.low, gw.close, gw.volume) == (775.0, 779.0, 741.0, 756.0, 9849934)


@pytest.mark.asyncio
async def test_stocks_without_a_regular_session_trade_have_no_close(requests: list[httpx.Request]) -> None:
    closes = await make_provider().get_latest_closes()

    assert {"1213", "1538", "2035"}.isdisjoint(closes)


@pytest.mark.asyncio
async def test_a_zero_close_is_no_close(payloads: dict[str, list[dict[str, str]]], requests: list[httpx.Request]) -> None:
    tsmc = next(row for row in payloads[SOURCES.exchange.twse_daily_quotes_url] if row["Code"] == "2330")
    tsmc["ClosingPrice"] = "0.00"

    closes = await make_provider().get_latest_closes()

    assert "2330" not in closes
    assert "1101" in closes


@pytest.mark.asyncio
async def test_reads_at_once_of_an_empty_stock_list_download_it_once(monkeypatch, payloads: dict[str, list[dict[str, str]]]) -> None:
    sent: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=payloads[str(request.url)])

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    provider = make_provider()

    every_stock, one_stock, closes = await asyncio.gather(provider.get_all(), provider.get_by_id("1101"), provider.get_latest_closes())

    assert sorted(sent) == sorted(PAYLOADS)
    assert one_stock is not None and one_stock.stock_id in {stock.stock_id for stock in every_stock} and "1101" in closes


@pytest.mark.asyncio
async def test_closes_come_from_the_cached_stock_list_download(requests: list[httpx.Request]) -> None:
    provider = make_provider()

    await provider.get_all()
    closes = await provider.get_latest_closes()

    assert closes["1101"].close == 28.2
    assert sorted(str(request.url) for request in requests) == sorted(PAYLOADS)


@pytest.mark.asyncio
async def test_each_close_carries_the_change_its_listing_reports(requests: list[httpx.Request]) -> None:
    """TWSE writes '-10.0000', TPEX '-58.00 ' with a trailing space."""
    closes = await make_provider().get_latest_closes()

    assert {stock_id: bar.change for stock_id, bar in closes.items()} == {"1101": 0.2, "2330": -10.0, "6488": -58.0, "8069": -4.0}


@pytest.mark.parametrize(("text", "change"), [("+1.50", 1.5), ("--- ", None), ("nan", None), ("149.00", None)])
@pytest.mark.asyncio
async def test_a_change_that_is_no_number_or_leaves_no_reference_price_keeps_the_close_without_one(
    payloads: dict[str, list[dict[str, str]]], requests: list[httpx.Request], text: str, change: float | None
) -> None:
    """A 149.00 close cannot have risen by 149.00: its reference price would be 0."""
    row = next(row for row in payloads[SOURCES.exchange.tpex_daily_quotes_url] if row["SecuritiesCompanyCode"] == "8069")
    row["Change"] = text

    closes = await make_provider().get_latest_closes()

    assert (closes["8069"].close, closes["8069"].change) == (149.0, change)
