"""
A personal site's daily history comes from the exchanges' own reports of each date, read from answers recorded on
2026-11-07 (tests/fixtures/exchange_reports): TWSE's MI_INDEX and TPEX's closing quotes of 2025-07-22, both of the
Saturday 2025-07-19, and each exchange's index reports of June and July 2025, trimmed to the sessions around the month's
turn; and TWSE's ex-right references (TWT49U) of 2025's third quarter, recorded on 2026-11-12 and trimmed to four rows.
"""

import asyncio
import json
import time
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from support.settings import shipped_config
from trading_stack import SilentLogger

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.types.enums import MarketType
from b_application.config.market_data_config import MarketDataConfig, MarketHoursConfig
from c_infrastructure.market.exchange_daily_reports import ExchangeDailyReports
from c_infrastructure.request_pace import RequestPace
from c_infrastructure.system.market_clock import TaiwanMarketClock

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).parent / "fixtures" / "exchange_reports"
CLOCK = TaiwanMarketClock(MarketHoursConfig())
TUESDAY, SATURDAY = date(2025, 7, 22), date(2025, 7, 19)
RECORDED = {
    ("/rwd/zh/afterTrading/MI_INDEX", "20250722"): "twse_mi_index_20250722.json",
    ("/rwd/zh/afterTrading/MI_INDEX", "20250719"): "twse_mi_index_20250719.json",
    ("/www/zh-tw/afterTrading/otc", "2025/07/22"): "tpex_otc_20250722.json",
    ("/www/zh-tw/afterTrading/otc", "2025/07/19"): "tpex_otc_20250719.json",
    ("/rwd/zh/TAIEX/MI_5MINS_HIST", "20250701"): "twse_mi_5mins_hist_202507.json",
    ("/rwd/zh/afterTrading/FMTQIK", "20250701"): "twse_fmtqik_202507.json",
    ("/www/zh-tw/indexInfo/inx", "2025/07/01"): "tpex_inx_202507.json",
    ("/www/zh-tw/afterTrading/tradingIndex", "2025/07/01"): "tpex_trading_index_202507.json",
    ("/rwd/zh/TAIEX/MI_5MINS_HIST", "20250601"): "twse_mi_5mins_hist_202506.json",
    ("/rwd/zh/afterTrading/FMTQIK", "20250601"): "twse_fmtqik_202506.json",
    ("/www/zh-tw/indexInfo/inx", "2025/06/01"): "tpex_inx_202506.json",
    ("/www/zh-tw/afterTrading/tradingIndex", "2025/06/01"): "tpex_trading_index_202506.json",
}


def serve(
    monkeypatch: pytest.MonkeyPatch,
    asked: list[tuple[str, str, float]],
    refused: frozenset[str] = frozenset(),
    recorded: Mapping[tuple[str, str], str | dict[str, Any]] = RECORDED,
) -> None:
    """
    Every request answers its `recorded` report, a fixture's name or an answer itself, or 307 with no Location (TWSE's
    refusal) for a host in `refused`.
    """
    real_client = httpx.AsyncClient

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append((request.url.host, request.url.params["date"], time.monotonic()))

        if request.url.host in refused:
            return httpx.Response(307, text="FOR SECURITY REASONS")

        report = recorded[(request.url.path, request.url.params["date"])]
        return (
            httpx.Response(200, json=report) if isinstance(report, dict) else httpx.Response(200, text=(FIXTURES / report).read_text())
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(answer)))


def reports(paces: dict[MarketType, RequestPace] | None = None, interval_seconds: float = 0) -> ExchangeDailyReports:
    exchange, market_data = shipped_config().sources.exchange, MarketDataConfig(history_request_interval_seconds=interval_seconds)
    return ExchangeDailyReports(
        feeds=exchange.daily_reports,
        ex_right_feed=exchange.ex_right_references,
        request_paces=paces or {market: RequestPace() for market in MarketType},
        market_clock=CLOCK,
        market_data=market_data,
        board_lot_shares=1000,
        logger=SilentLogger(),
    )


def bar(close: float, open_price: float, high: float, low: float, volume: int, change: float | None) -> Ohlcv:
    return Ohlcv(ts=CLOCK.session_close(TUESDAY), open=open_price, high=high, low=low, close=close, volume=volume, change=change)


async def test_a_session_is_every_traded_four_digit_stock_of_both_exchanges_with_its_change(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[str, str, float]] = []
    serve(monkeypatch, asked)

    bars = await reports().session_bars(TUESDAY)

    assert bars == {
        "0050": bar(50.55, 50.90, 51.30, 50.45, 92_162_175, -0.35),
        "2330": bar(1130.0, 1145.0, 1160.0, 1130.0, 54_933_274, -20.0),
        "1303": bar(28.80, 29.10, 29.35, 28.75, 17_700_187, None),
        "3611": bar(187.0, 186.0, 188.0, 185.5, 127_000, None),
        "6488": bar(333.5, 349.5, 349.5, 333.0, 3_680_000, -15.5),
    }
    assert [(host, day) for host, day, _ in asked] == [("www.twse.com.tw", "20250722"), ("www.tpex.org.tw", "2025/07/22")]


@pytest.mark.parametrize(
    ("twse", "tpex", "asked_sites"),
    [
        ("twse_mi_index_20250719.json", "tpex_otc_20250719.json", ["www.twse.com.tw"]),
        ("twse_mi_index_20250722.json", "tpex_otc_20250719.json", ["www.twse.com.tw", "www.tpex.org.tw"]),
        ("twse_mi_index_20250719.json", "tpex_otc_20250722.json", ["www.twse.com.tw"]),
    ],
    ids=["no-session", "tpex-not-served-yet", "twse-of-another-date"],
)
async def test_a_session_that_either_exchange_does_not_serve_has_no_bars(
    monkeypatch: pytest.MonkeyPatch, twse: str, tpex: str, asked_sites: list[str]
) -> None:
    """A date the answer does not name counts as none: the Saturday's TWSE answer serves the Tuesday asked here."""
    asked: list[tuple[str, str, float]] = []
    recorded = {("/rwd/zh/afterTrading/MI_INDEX", "20250722"): twse, ("/www/zh-tw/afterTrading/otc", "2025/07/22"): tpex}
    serve(monkeypatch, asked, recorded=recorded)

    assert await reports().session_bars(TUESDAY) == {}
    assert [host for host, _, _ in asked] == asked_sites


async def test_a_report_without_the_fields_it_had_raises_instead_of_serving_no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    tuesday = json.loads((FIXTURES / "twse_mi_index_20250722.json").read_text())
    renamed = {**tuesday, "tables": [{**table, "fields": [f"{name}2" for name in table["fields"]]} for table in tuesday["tables"]]}
    serve(monkeypatch, [], recorded={**RECORDED, ("/rwd/zh/afterTrading/MI_INDEX", "20250722"): renamed})

    with pytest.raises(ValueError, match="no table of the fields"):
        await reports().session_bars(TUESDAY)


async def test_an_index_is_each_session_of_the_months_asked_with_its_official_change_and_volume_in_shares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[str, str, float]] = []
    serve(monkeypatch, asked)
    source = reports()

    twse = await source.index_bars(MarketType.TWSE, date(2025, 6, 30), date(2025, 7, 1))
    tpex = await source.index_bars(MarketType.TPEX, date(2025, 7, 3), date(2025, 7, 4))

    def at(day: int, month: int = 7) -> datetime:
        return CLOCK.session_close(date(2025, month, day))

    assert twse == [
        Ohlcv(at(30, 6), 22508.33, 22558.95, 22256.02, 22256.02, 5_791_190_538, -324.06),
        Ohlcv(at(1), 22419.74, 22730.76, 22401.58, 22553.72, 6_415_082_209, 297.70),
    ]
    assert tpex == [
        Ohlcv(at(3), 233.13, 235.31, 233.13, 234.60, 791_673_000, 1.68),
        Ohlcv(at(4), 234.36, 235.36, 231.57, 231.61, 828_315_000, -2.99),
    ]
    assert [day for _, day, _ in asked] == ["20250601", "20250601", "20250701", "20250701", "2025/07/01", "2025/07/01"]


async def test_a_tpex_month_before_2025_names_its_volume_in_thousand_shares_and_reads_the_same(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fields and the first session TPEX served for November 2023, read on 2026-11-12."""
    prices = {
        "stat": "ok",
        "tables": [
            {
                "fields": ["日期", "開市", "最高", "最低", "收市", "漲/跌"],
                "data": [["2023/11/01", "209.96", "212.01", "209.96", "211.82", "2.17"]],
            }
        ],
    }
    volumes = {
        "stat": "ok",
        "tables": [
            {
                "fields": ["日期", "成交股數（仟股）", "金額（仟元）", "筆數", "櫃買指數", "漲/跌"],
                "data": [["112/11/01", "587,692", "54,227,965", "454,411", 211.82, 2.17]],
            }
        ],
    }
    recorded = {("/www/zh-tw/indexInfo/inx", "2023/11/01"): prices, ("/www/zh-tw/afterTrading/tradingIndex", "2023/11/01"): volumes}
    serve(monkeypatch, [], recorded=recorded)

    bars = await reports().index_bars(MarketType.TPEX, date(2023, 11, 1), date(2023, 11, 1))

    assert bars == [Ohlcv(CLOCK.session_close(date(2023, 11, 1)), 209.96, 212.01, 209.96, 211.82, 587_692_000, 2.17)]


async def test_requests_to_one_site_wait_the_interval_whichever_runtime_asks_and_the_other_site_does_not_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[str, str, float]] = []
    serve(monkeypatch, asked)
    paces = {market: RequestPace() for market in MarketType}
    retired, current = reports(paces, interval_seconds=0.3), reports(paces, interval_seconds=0.3)
    start = time.monotonic()

    await asyncio.gather(retired.session_bars(TUESDAY), current.session_bars(TUESDAY))

    twse = [moment for host, _, moment in asked if host == "www.twse.com.tw"]
    tpex = [moment for host, _, moment in asked if host == "www.tpex.org.tw"]
    assert twse[1] >= start + 0.3 and tpex[1] >= start + 0.3
    assert [host for host, _, _ in asked] == ["www.twse.com.tw", "www.tpex.org.tw", "www.twse.com.tw", "www.tpex.org.tw"]


async def test_a_site_that_refuses_the_address_fails_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, [], refused=frozenset({"www.tpex.org.tw"}))

    with pytest.raises(httpx.HTTPStatusError, match="307"):
        await reports().session_bars(TUESDAY)


async def test_twses_ex_right_references_of_a_range_are_each_four_digit_stocks_reference_price_by_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []
    real_client = httpx.AsyncClient

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, text=(FIXTURES / "twse_twt49u_2025q3.json").read_text())

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(answer)))

    references = await reports().ex_right_references(MarketType.TWSE, date(2025, 7, 1), date(2025, 9, 30))

    assert asked == ["https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20250701&endDate=20250930&response=json"]
    assert references == {("1101", date(2025, 7, 2)): 25.15, ("0050", date(2025, 7, 21)): 51.09, ("2330", date(2025, 9, 16)): 1249.99}


async def test_a_range_without_an_ex_right_day_has_no_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """TWSE's answer for 2027-01-01 to 2027-01-05, read on 2026-11-14."""
    real_client = httpx.AsyncClient
    empty = {"stat": "很抱歉，沒有符合條件的資料!"}
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=empty))),
    )

    assert await reports().ex_right_references(MarketType.TWSE, date(2025, 1, 1), date(2025, 1, 5)) == {}


@pytest.mark.parametrize("market", list(MarketType))
async def test_a_range_an_exchange_refuses_in_json_is_not_read_as_one_without_an_ex_right_day(
    monkeypatch: pytest.MonkeyPatch, market: MarketType
) -> None:
    """TWSE's answer to a range it refuses, read on 2026-11-14: a `stat` alone, as for a range without an ex-day."""
    real_client = httpx.AsyncClient
    refusal = {"stat": "開始日期大於結束日期，請重新查詢!"}
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=refusal))),
    )

    with pytest.raises(ValueError, match="開始日期大於結束日期"):
        await reports().ex_right_references(market, date(2025, 1, 1), date(2025, 1, 5))


async def test_tpexs_ex_right_references_of_a_range_are_each_four_digit_stocks_reference_price_by_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []
    real_client = httpx.AsyncClient

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, text=(FIXTURES / "tpex_exdailyq_2025q3.json").read_text())

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(answer)))

    references = await reports().ex_right_references(MarketType.TPEX, date(2025, 7, 1), date(2025, 9, 30))

    assert asked == ["https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate=2025/07/01&endDate=2025/09/30&response=json"]
    assert references == {("2230", date(2025, 7, 1)): 102.5, ("6488", date(2025, 7, 16)): 304.0, ("8069", date(2025, 7, 24)): 211.01}


async def test_a_tpex_range_without_an_ex_right_day_has_no_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    real_client = httpx.AsyncClient
    empty = {"date": "20261114~20261114", "tables": [{"fields": ["除權息日期", "代號", "除權息參考價"], "data": []}], "stat": "ok"}
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=empty))),
    )

    assert await reports().ex_right_references(MarketType.TPEX, date(2026, 11, 14), date(2026, 11, 14)) == {}
