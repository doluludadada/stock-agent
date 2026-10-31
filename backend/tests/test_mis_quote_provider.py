import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from trading_stack import SilentLogger

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.types.enums import MarketType
from b_application.config.market_data_config import MarketDataConfig
from b_application.config.sources_config import SourcesConfig
from c_infrastructure.market.mis_quote_provider import MisQuoteProvider
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

SOURCES = SourcesConfig()

# getStockInfo.jsp as served on Saturday 2026-10-31 02:40 Taipei, holding the final quotes of the 2026-10-30 session.
# 2330 (TWSE) and 6488 (TPEX) last traded in the 13:30 closing auction. 1233 (TWSE) and 1240 (TPEX) last traded earlier,
# so their z is "-" and their trade object holds that trade. 1470 did not trade at all. 9999 is not listed.
SAVED_RESPONSE = json.loads((Path(__file__).parent / "fixtures" / "twse_mis_getstockinfo.json").read_text(encoding="utf-8"))
TSMC = Stock(stock_id="2330")
GLOBALWAFERS = Stock(stock_id="6488", market=MarketType.TPEX)


def traded_at(hour: int, minute: int, second: int) -> datetime:
    return datetime(2026, 10, 30, hour, minute, second, tzinfo=TAIWAN_TIMEZONE)


def test_each_quote_is_the_session_so_far_closing_at_the_last_trade_at_its_trade_time() -> None:
    assert provider().parse_quotes(SAVED_RESPONSE) == {
        "2330": Ohlcv(ts=traded_at(13, 30, 0), open=2380.0, high=2380.0, low=2360.0, close=2370.0, volume=29_562_000),
        "6488": Ohlcv(ts=traded_at(13, 30, 0), open=775.0, high=779.0, low=741.0, close=756.0, volume=8_913_000),
        "1233": Ohlcv(ts=traded_at(13, 1, 26), open=28.2, high=28.2, low=28.2, close=28.2, volume=2_000),
        "1240": Ohlcv(ts=traded_at(9, 51, 7), open=54.0, high=54.0, low=53.3, close=53.7, volume=7_000),
    }


def test_a_stock_without_a_trade_this_session_has_no_quote() -> None:
    quotes = provider().parse_quotes(SAVED_RESPONSE)

    assert "1470" not in quotes
    assert "" not in quotes


def test_a_refused_request_is_an_error_not_an_empty_answer() -> None:
    with pytest.raises(ValueError, match="9999"):
        provider().parse_quotes({"rtcode": "9999", "rtmessage": "參數不足"})


@pytest.fixture
def channels_requested(monkeypatch) -> list[list[str]]:
    """Serves the saved response to every request and records the ex_ch channels each request asked for."""
    requested: list[list[str]] = []
    real_client = httpx.AsyncClient

    def answer(request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        assert str(request.url).split("?")[0] == SOURCES.exchange.mis_quotes_url
        assert (query["json"], query["delay"]) == (["1"], ["0"])
        requested.append(query["ex_ch"][0].split("|"))
        return httpx.Response(200, json=SAVED_RESPONSE)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(answer)))
    return requested


def provider(request_interval_seconds: float = 0.0) -> MisQuoteProvider:
    return MisQuoteProvider(
        SOURCES.exchange, MarketDataConfig(quote_request_interval_seconds=request_interval_seconds), SilentLogger()
    )


@pytest.mark.asyncio
async def test_quotes_are_requested_per_market_channel_and_returned_for_the_requested_stocks(
    channels_requested: list[list[str]],
) -> None:
    quotes = await provider().fetch_realtime_bars([TSMC, GLOBALWAFERS, Stock(stock_id="1470")])

    assert channels_requested == [["tse_2330.tw", "otc_6488.tw", "tse_1470.tw"]]
    assert sorted(quotes) == ["2330", "6488"]
    assert quotes["6488"].close == 756.0


@pytest.mark.asyncio
async def test_stocks_are_deduplicated_and_requested_fifty_per_request(channels_requested: list[list[str]]) -> None:
    stocks = [Stock(stock_id=f"{code:04d}") for code in range(1100, 1220)]

    await provider().fetch_realtime_bars(stocks + stocks[:10])

    assert [len(channels) for channels in channels_requested] == [50, 50, 20]
    assert channels_requested[0][0] == "tse_1100.tw"
    assert channels_requested[2][-1] == "tse_1219.tw"


@pytest.mark.asyncio
async def test_requests_are_spaced_by_the_request_interval(channels_requested: list[list[str]]) -> None:
    quotes = provider(request_interval_seconds=0.3)
    started = time.monotonic()

    await quotes.fetch_realtime_bars([TSMC])
    await quotes.fetch_realtime_bars([TSMC])

    assert len(channels_requested) == 2
    assert time.monotonic() - started >= 0.3


@pytest.mark.asyncio
async def test_no_stocks_means_no_request(channels_requested: list[list[str]]) -> None:
    assert await provider().fetch_realtime_bars([]) == {}
    assert channels_requested == []


@pytest.mark.asyncio
async def test_an_http_failure_propagates(monkeypatch) -> None:
    real_client = httpx.AsyncClient
    failing = httpx.MockTransport(lambda request: httpx.Response(503))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=failing))

    with pytest.raises(httpx.HTTPStatusError):
        await provider().fetch_realtime_bars([TSMC])
