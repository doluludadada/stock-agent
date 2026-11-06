import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from support.settings import shipped_config
from trading_stack import MovableClock

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.daily_close_archive import ValuationRatios
from a_domain.types.enums import EpsKind, MarketType
from a_domain.types.values import FiscalQuarter
from b_application.config.market_data_config import MarketDataConfig, MarketHoursConfig
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.system.market_clock import TaiwanMarketClock

SOURCES = shipped_config().sources

FIXTURES = Path(__file__).parent / "fixtures"

# Trimmed real responses: STOCK_DAY_ALL as served on 2026-10-30 (session 2026-10-29) and the TPEX close quotes
# for 2026-10-30. 1213 and 1538 (TWSE) and 2035 (TPEX) did not trade in the regular session. MI_INDEX and tpex_index
# as both served at 16:25 on 2026-11-06: three of MI_INDEX's 267 indexes of the session 2026-11-05, and the TPEx Index
# of 2026-11-02 to 2026-11-06.
LISTINGS = {
    SOURCES.exchange.twse_daily_quotes_url: json.loads((FIXTURES / "twse_stock_day_all.json").read_text(encoding="utf-8")),
    SOURCES.exchange.tpex_daily_quotes_url: json.loads(
        (FIXTURES / "tpex_mainboard_daily_close_quotes.json").read_text(encoding="utf-8")
    ),
}
PAYLOADS = LISTINGS | {
    SOURCES.exchange.twse_index_url: json.loads((FIXTURES / "twse_mi_index.json").read_text(encoding="utf-8")),
    SOURCES.exchange.tpex_index_url: json.loads((FIXTURES / "tpex_index.json").read_text(encoding="utf-8")),
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
async def test_a_null_listing_field_loses_only_its_own_stock_or_value(
    payloads: dict[str, list[dict[str, str | None]]], requests: list[httpx.Request]
) -> None:
    twse = payloads[SOURCES.exchange.twse_daily_quotes_url]
    tsmc = next(row for row in twse if row["Code"] == "2330")
    cement = next(row for row in twse if row["Code"] == "1101")
    twse.append({**tsmc, "Code": None})
    tsmc["Name"], cement["ClosingPrice"] = None, None
    provider = make_provider()

    stocks = {stock.stock_id: stock.name for stock in await provider.get_all()}
    closes = await provider.get_latest_closes()

    assert "None" not in stocks and stocks["2330"] == ""
    assert ("1101" in stocks, "1101" in closes, "2330" in closes) == (True, False, True)


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

    assert sorted(sent) == sorted(LISTINGS)
    assert one_stock is not None and one_stock.stock_id in {stock.stock_id for stock in every_stock} and "1101" in closes


@pytest.mark.asyncio
async def test_closes_come_from_the_cached_stock_list_download(requests: list[httpx.Request]) -> None:
    provider = make_provider()

    await provider.get_all()
    closes = await provider.get_latest_closes()

    assert closes["1101"].close == 28.2
    assert sorted(str(request.url) for request in requests) == sorted(LISTINGS)


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


def session_closes(bars: list[Ohlcv]) -> list[tuple[str, float, float | None]]:
    return [(bar.ts.isoformat(), bar.close, bar.change) for bar in bars]


@pytest.mark.asyncio
async def test_index_closes_are_the_taiex_and_the_tpex_index_under_their_own_sessions(requests: list[httpx.Request]) -> None:
    closes = await make_provider().fetch_index_closes()

    assert session_closes(closes[MarketType.TWSE]) == [("2026-11-05T13:30:00+08:00", 41574.72, -1374.19)]
    assert session_closes(closes[MarketType.TPEX]) == [
        ("2026-11-02T13:30:00+08:00", 369.24, -1.02),
        ("2026-11-03T13:30:00+08:00", 345.52, -23.72),
        ("2026-11-04T13:30:00+08:00", 343.5, -2.02),
        ("2026-11-05T13:30:00+08:00", 321.47, -22.03),
        ("2026-11-06T13:30:00+08:00", 304.02, -17.45),
    ]


@pytest.mark.asyncio
async def test_a_rising_taiex_has_a_positive_change_and_a_row_without_a_close_or_a_date_is_skipped(
    payloads: dict[str, list[dict[str, str]]], requests: list[httpx.Request]
) -> None:
    taiex = next(row for row in payloads[SOURCES.exchange.twse_index_url] if row["指數"] == "發行量加權股價指數")
    taiex["漲跌"] = "+"
    tpex = payloads[SOURCES.exchange.tpex_index_url]
    tpex[0]["Close"], tpex[1]["Date"] = "--", ""

    closes = await make_provider().fetch_index_closes()

    assert session_closes(closes[MarketType.TWSE]) == [("2026-11-05T13:30:00+08:00", 41574.72, 1374.19)]
    assert [bar.ts.date().isoformat() for bar in closes[MarketType.TPEX]] == ["2026-11-04", "2026-11-05", "2026-11-06"]


@pytest.mark.asyncio
async def test_an_index_row_with_a_null_date_or_close_is_skipped_and_a_null_change_leaves_the_close_without_one(
    payloads: dict[str, list[dict[str, str | None]]], requests: list[httpx.Request]
) -> None:
    twse = payloads[SOURCES.exchange.twse_index_url]
    taiex = next(row for row in twse if row["指數"] == "發行量加權股價指數")
    twse += [{**taiex, "日期": None}, {**taiex, "收盤指數": None}]
    taiex["漲跌"], taiex["漲跌點數"] = None, None
    tpex = payloads[SOURCES.exchange.tpex_index_url]
    tpex[0]["Close"], tpex[1]["Date"], tpex[2]["Change"] = None, None, None

    closes = await make_provider().fetch_index_closes()

    assert session_closes(closes[MarketType.TWSE]) == [("2026-11-05T13:30:00+08:00", 41574.72, None)]
    assert session_closes(closes[MarketType.TPEX]) == [
        ("2026-11-04T13:30:00+08:00", 343.5, None),
        ("2026-11-05T13:30:00+08:00", 321.47, -22.03),
        ("2026-11-06T13:30:00+08:00", 304.02, -17.45),
    ]


@pytest.mark.asyncio
async def test_an_index_report_that_fails_leaves_out_only_its_exchange(monkeypatch, payloads: dict[str, list[dict[str, str]]]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == SOURCES.exchange.tpex_index_url:
            return httpx.Response(503)

        return httpx.Response(200, json=payloads[str(request.url)])

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))

    closes = await make_provider().fetch_index_closes()

    assert list(closes) == [MarketType.TWSE]


@pytest.mark.asyncio
async def test_industries_merge_every_market_and_refetch_a_market_only_once_its_profiles_are_a_day_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = MovableClock(
        datetime(2026, 11, 6, 9, 0, tzinfo=TaiwanMarketClock(MarketHoursConfig()).session_close(date(2026, 11, 6)).tzinfo)
    )
    logger = SimpleNamespace(debug=lambda message: None, success=lambda message: None, error=lambda message: None)
    provider = TaiwanStockProvider(SOURCES.exchange, clock, MarketDataConfig(), cast(Any, logger))
    profiles = {
        MarketType.TWSE: [{"公司代號": "2330", "產業別": "24"}],
        MarketType.TPEX: [{"SecuritiesCompanyCode": "6488", "SecuritiesIndustryCode": "24"}],
    }
    down = {MarketType.TPEX}
    requests: list[MarketType] = []

    async def fetch_reports(urls: dict[MarketType, str]) -> dict[MarketType, list[dict[str, Any]]]:
        requests.extend(urls)
        return {market: profiles[market] for market in urls if market not in down}

    monkeypatch.setattr(provider, "fetch_reports", fetch_reports)

    assert await provider.fetch_industries() == {"2330": "半導體業"}

    down.clear()
    clock.current += timedelta(hours=1)
    assert await provider.fetch_industries() == {"2330": "半導體業", "6488": "半導體業"}

    down.add(MarketType.TWSE)
    clock.current += timedelta(hours=24)
    assert await provider.fetch_industries() == {"2330": "半導體業", "6488": "半導體業"}
    assert requests == [MarketType.TWSE, MarketType.TPEX, MarketType.TPEX, MarketType.TWSE, MarketType.TPEX]


@pytest.mark.asyncio
async def test_industries_come_from_every_companys_profile_and_name_its_industry_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trimmed rows of t187ap03_L and mopsfin_t187ap03_O as served on 2026-11-04. 91 (depositary receipts) has no name."""
    profiles = {
        SOURCES.exchange.company_profiles[MarketType.TWSE].url: [
            {"公司代號": "1101", "公司簡稱": "台泥", "產業別": "01"},
            {"公司代號": "2330", "公司簡稱": "台積電", "產業別": "24"},
            {"公司代號": "9103", "公司簡稱": "美德醫療-DR", "產業別": "91"},
        ],
        SOURCES.exchange.company_profiles[MarketType.TPEX].url: [
            {"SecuritiesCompanyCode": "6488", "CompanyAbbreviation": "環球晶", "SecuritiesIndustryCode": "24"},
            {"SecuritiesCompanyCode": "8069", "CompanyAbbreviation": "元太", "SecuritiesIndustryCode": "26"},
        ],
    }
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=profiles[str(request.url)]))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport))

    assert await make_provider().fetch_industries() == {"1101": "水泥工業", "2330": "半導體業", "6488": "半導體業", "8069": "光電業"}


def test_an_announcement_without_a_valid_date_time_or_company_is_left_out_and_a_blank_fact_date_is_none() -> None:
    provider, fetched_at = (
        make_provider(),
        datetime(2026, 11, 6, 10, 0, tzinfo=TaiwanMarketClock(MarketHoursConfig()).session_close(date(2026, 11, 6)).tzinfo),
    )
    row = {
        "公司代號": "2330",
        "發言日期": "1151105",
        "發言時間": "90501",
        "主旨 ": "subject",
        "符合條款": "第51款",
        "事實發生日": "",
        "說明": "text",
    }

    announcement = provider.parse_announcement(row, MarketType.TWSE, fetched_at)

    assert announcement is not None and announcement.published_at.isoformat() == "2026-11-05T09:05:01+08:00"
    assert (announcement.title, announcement.content, announcement.clause, announcement.fact_date) == (
        "subject",
        "text",
        "第51款",
        None,
    )
    for broken in ({"發言日期": "115/11/05"}, {"發言時間": "250000"}, {"公司代號": " "}):
        assert provider.parse_announcement(row | broken, MarketType.TWSE, fetched_at) is None


def test_quarter_eps_is_the_year_to_date_figure_of_the_quarter_its_row_names_and_a_row_without_one_is_left_out() -> None:
    rows = [
        {"SecuritiesCompanyCode": "1268", "Year": "115", "季別": "3", "基本每股盈餘": "11.20"},
        {"SecuritiesCompanyCode": "1796", "Year": "114", "季別": "4", "基本每股盈餘": "-0.21"},
        {"SecuritiesCompanyCode": "1565", "Year": "115", "季別": "5", "基本每股盈餘": "4.58"},
        {"SecuritiesCompanyCode": "1570", "Year": "115", "季別": "3", "基本每股盈餘": ""},
    ]

    filed = make_provider().parse_quarter_eps(rows, MarketType.TPEX)

    assert {stock_id: (eps.value, eps.period_end, eps.kind) for stock_id, eps in filed.items()} == {
        "1268": (11.2, FiscalQuarter(2026, 3), EpsKind.CUMULATIVE),
        "1796": (-0.21, FiscalQuarter(2025, 4), EpsKind.CUMULATIVE),
    }


def test_valuation_ratios_keep_the_session_their_row_names_and_a_blank_ratio_as_none() -> None:
    rows = [
        {"Date": "1151105", "Code": "1101", "Name": "台泥", "PEratio": "", "DividendYield": "2.94", "PBratio": "0.88"},
        {"Date": "1151104", "Code": "2330", "Name": "台積電", "PEratio": "1,025.96", "DividendYield": "-", "PBratio": "9.03"},
        {"Date": "", "Code": "2317", "Name": "鴻海", "PEratio": "15.49", "DividendYield": "3.05", "PBratio": "1.73"},
    ]

    assert make_provider().parse_valuation_ratios(rows, MarketType.TWSE) == [
        ValuationRatios(stock_id="1101", session_date=date(2026, 11, 5), pe_ratio=None, dividend_yield=2.94, pb_ratio=0.88),
        ValuationRatios(stock_id="2330", session_date=date(2026, 11, 4), pe_ratio=1025.96, dividend_yield=None, pb_ratio=9.03),
    ]
