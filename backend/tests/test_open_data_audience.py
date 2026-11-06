"""
A public deployment (audience public) runs on open-licensed data only. Through the real wiring it never builds the
Yahoo, TWSE MIS, news site, PTT, MOPS, web search or Shioaji adapter and reads its daily history and index trend from
the open-data archive alone, with Yahoo's cache beside it untouched; a specific-stock run completes without an
article and without an AI call. Startup refuses it on a real broker. Its Web API and its CLI refuse Buzz and Intraday,
which order on realtime quotes, and the valuation, which reads MOPS; menu 4 offers no manual BUY. Its AI step reads a
stock's archived material information and financials, and decides a stock with neither on its technical score alone.
Its runs say how far the archive's warm-up has come, and the market overview can read it, a stock's archived financials
and the open data's attribution. A personal deployment keeps every source and says nothing of the archive.
"""

import asyncio
import io
import json
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
import shioaji
from pydantic import SecretStr
from rich.console import Console
from support.harness import CliHarness, build_harness, harness_config, rising_history
from support.settings import environment_setup, shipped_config
from support.web import serve, write
from trading_stack import SilentLogger

from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.types.enums import (
    AiAnalysisFocus,
    AiProvider,
    Audience,
    ContentType,
    DatabaseBackend,
    ExecutionProvider,
    InformationSource,
    MarketIndex,
    MarketType,
    OrderMode,
    SettingsFile,
    SystemEnvironment,
)
from a_domain.types.values import FiscalQuarter
from b_application.config.app_config import AppConfig, DbConfig
from b_application.config.settings_loader import (
    InvalidSettingsError,
    TradingSetupError,
    get_project_root,
    load_settings,
    startup_settings,
    validate_trading_environment,
)
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.ohlcv_dto import OhlcvDTO
from c_infrastructure.feed.news.cnyes_news_provider import CnyesNewsProvider
from c_infrastructure.feed.news.yahoo_tw_news_provider import YahooTwNewsProvider
from c_infrastructure.feed.ptt_provider import PttProvider
from c_infrastructure.feed.tavily_provider import TavilySearchAdapter
from c_infrastructure.market.mis_quote_provider import MisQuoteProvider
from c_infrastructure.market.mops_fundamentals_provider import MopsFundamentalsProvider
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock
from d_presentation.cli import terminal
from d_presentation.dependencies import ProcessState, open_runtime
from d_presentation.web.schemas import AudienceResponse

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = get_project_root() / "config"
SOURCES = shipped_config().sources
KEY = SecretStr("A" * 43)
NOW = datetime(2026, 11, 6, 18, 0, tzinfo=TAIWAN_TIMEZONE)
"""The evening the fixtures' OpenAPI answers were saved: TWSE's listing then served 2026-10-29, MI_INDEX 2026-11-05."""

OPENAPI = {
    SOURCES.exchange.twse_daily_quotes_url: "twse_stock_day_all.json",
    SOURCES.exchange.tpex_daily_quotes_url: "tpex_mainboard_daily_close_quotes.json",
    SOURCES.exchange.twse_index_url: "twse_mi_index.json",
    SOURCES.exchange.tpex_index_url: "tpex_index.json",
    SOURCES.exchange.material_information[MarketType.TWSE].url: "twse_t187ap04_l.json",
    SOURCES.exchange.material_information[MarketType.TPEX].url: "tpex_mopsfin_t187ap04_o.json",
    SOURCES.exchange.quarter_eps[MarketType.TWSE].url: "twse_t187ap14_l.json",
    SOURCES.exchange.quarter_eps[MarketType.TPEX].url: "tpex_mopsfin_t187ap14_o.json",
    SOURCES.exchange.valuation_ratios[MarketType.TWSE].url: "twse_bwibbu_all.json",
    SOURCES.exchange.valuation_ratios[MarketType.TPEX].url: "tpex_mainboard_peratio_analysis.json",
}


def close_of(session: date) -> datetime:
    return datetime.combine(session, time(13, 30), TAIWAN_TIMEZONE)


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """
    Every URL asked over httpx. The OpenAPI endpoints the archive reads answer their trimmed real responses, anything
    else 503, and the market clock reads NOW.
    """
    answers = {url: json.loads((FIXTURES / name).read_text(encoding="utf-8")) for url, name in OPENAPI.items()}
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        rows = answers.get(str(request.url))
        return httpx.Response(503) if rows is None else httpx.Response(200, json=rows)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(TaiwanMarketClock, "now", lambda clock: NOW)
    return urls


CLOSED_SOURCES = (
    YahooFinanceProvider,
    MisQuoteProvider,
    CnyesNewsProvider,
    YahooTwNewsProvider,
    PttProvider,
    MopsFundamentalsProvider,
    TavilySearchAdapter,
)
"""Every adapter of a source whose terms a public site breaks: Yahoo, TWSE MIS, cnyes, Yahoo news, PTT, MOPS, Tavily."""


@pytest.fixture
def refused_adapters(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """
    Building any adapter of CLOSED_SOURCES or a Shioaji client fails the test, and each attempt is recorded by its class
    name, so a test can tell which one a deployment builds first.
    """
    attempts: list[str] = []

    def refusing(name: str) -> object:
        def refuse(*args: object, **kwargs: object) -> None:
            attempts.append(name)
            raise AssertionError(f"built {name}, an adapter an open-data deployment must never build")

        return refuse

    for adapter in CLOSED_SOURCES:
        monkeypatch.setattr(adapter, "__init__", refusing(adapter.__name__))

    monkeypatch.setattr(shioaji, "Shioaji", refusing("Shioaji"))
    return attempts


def deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, audience: Audience) -> AppConfig:
    """
    The shipped settings for `audience` on the mock broker, over a SQLite file and a Chroma folder in tmp_path, with a
    Tavily key set and the AI's web search switched on where startup allows it: only on an audience with news articles.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    monkeypatch.setenv("GROQ_API_KEY", "placeholder")
    monkeypatch.setenv("TAVILY_API_KEY", "placeholder")
    shipped = load_settings(get_project_root()).model_copy(update={"project_root": tmp_path, "audience": audience})
    shipped.behavior.enable_web_search = audience == Audience.PERSONAL
    shipped.ai.user_selectable = [*shipped.ai.user_selectable, AiProvider.GROQ]
    config = environment_setup(shipped, SystemEnvironment.DEV, ExecutionProvider.MOCK, OrderMode.MOCK_ONLY)
    config.accounts.key = KEY
    config.db = DbConfig(_env_file=None, backend=DatabaseBackend.SQLITE, chroma_persist_path=str(tmp_path / "chroma"))
    validate_trading_environment(config)
    return config


def process() -> ProcessState:
    return ProcessState(logger=SilentLogger(), attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())


async def cache_yahoo_bars(config: AppConfig, bars: dict[str, list[Ohlcv]]) -> None:
    """Bars in Yahoo's cache (ohlcv_data), as a personal deployment's runs left them."""
    database = DatabaseConnector(config=config, logger=SilentLogger())
    await database.init_db()

    try:
        async with database.get_session() as session:
            for key, rows in bars.items():
                for bar in rows:
                    await session.merge(OhlcvDTO(stock_id=key, **asdict(bar)))

            await session.commit()
    finally:
        await database.close()


async def test_a_public_deployment_builds_no_closed_source_adapter_and_completes_a_run_without_articles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asked: list[str], refused_adapters: list[str]
) -> None:
    config = deployment(tmp_path, monkeypatch, Audience.PUBLIC)
    yahoo = [Ohlcv(ts=close_of(date(2026, 10, day)), open=1.0, high=1.0, low=1.0, close=1.0, volume=1) for day in (28, 29)]
    await cache_yahoo_bars(config, {"2330": yahoo, "^taiex": yahoo})

    async with open_runtime(config, process()) as runtime:
        await runtime.signed_out.archive_daily_closes()
        history = await runtime.signed_out.load_stock_history("2330", 20)
        taiex = await runtime.signed_out.load_index_history(MarketIndex.TAIEX, 20)
        owner = await runtime.signed_out.set_up_first_administrator("owner", "owner@example.com", SecretStr("a long password"))
        full_cycle = await runtime.pipeline_for(owner).run_full_cycle()
        specific = await runtime.pipeline_for(owner).analyse_specific_stocks(["2330"])

    [stock] = history.manual_stocks
    [report] = specific.manual_stocks
    assert [(bar.ts, bar.open, bar.close) for bar in stock.ohlcv] == [(close_of(date(2026, 10, 29)), 2420.0, 2415.0)]
    assert [(bar.ts, bar.open, bar.high, bar.low, bar.close) for bar in taiex] == [
        (close_of(date(2026, 11, 5)), 41574.72, 41574.72, 41574.72, 41574.72)
    ]
    assert full_cycle.stats.failure is None and full_cycle.stats.passed_technical == 0
    assert "The open-data archive holds 2 of the 61 sessions needed" in " ".join(full_cycle.stats.errors)
    assert specific.stats.failure is None and specific.stats.ai_analysed == 0
    assert (report.stock_id, report.articles, report.ai_report, report.composite_score) == ("2330", [], None, report.technical_score)
    assert any("2330: nothing to read. This site reads no news site" in line for line in specific.stats.execution_log)
    assert {urlsplit(url).hostname for url in asked} == {"openapi.twse.com.tw", "www.tpex.org.tw"}
    assert refused_adapters == []


async def test_a_personal_deployment_builds_the_closed_source_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused_adapters: list[str]
) -> None:
    with pytest.raises(AssertionError, match="must never build"):
        async with open_runtime(deployment(tmp_path, monkeypatch, Audience.PERSONAL), process()):
            pass

    assert refused_adapters != []


@pytest.mark.parametrize("environment", [SystemEnvironment.TEST, SystemEnvironment.PROD])
async def test_startup_refuses_a_public_deployment_on_a_real_broker_and_allows_a_personal_one(environment: SystemEnvironment) -> None:
    real_broker = environment_setup(harness_config(), environment, ExecutionProvider.SHIOAJI, OrderMode.DISABLED)
    validate_trading_environment(real_broker)

    with pytest.raises(TradingSetupError) as refused:
        validate_trading_environment(real_broker.model_copy(update={"audience": Audience.PUBLIC}))

    assert refused.value.path == "trading.execution_provider"
    assert str(refused.value).startswith("audience public trades only on mock, not shioaji")


async def test_the_start_names_the_line_of_a_public_audience_on_a_real_broker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "config").symlink_to(CONFIG)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    text = (CONFIG / "appsetting.yaml").read_text(encoding="utf-8")
    text = text.replace("environment: dev", "environment: test", 1).replace("audience: personal", "audience: public", 1)
    text = text.replace(
        "  execution_provider: mock\n  order_mode: mock_only", "  execution_provider: shioaji\n  order_mode: disabled", 1
    )

    with pytest.raises(InvalidSettingsError) as refused:
        startup_settings(tmp_path, {SettingsFile.APPSETTING: text})

    [problem] = refused.value.problems
    assert (problem.path, problem.line) == (
        "trading.execution_provider",
        text[: text.index("execution_provider: shioaji")].count("\n") + 1,
    )
    assert "audience public trades only on mock" in problem.message


def public_harness(sessions: int) -> CliHarness:
    """The harness on audience public with 2330 listed, its archive holding `sessions` sessions of stock closes."""
    harness = build_harness(config=harness_config().model_copy(update={"audience": Audience.PUBLIC}))
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    bar = rising_history(100.0)[-1]
    harness.archive.stock_closes = {("2330", bar.ts.date() - timedelta(days=day)): bar for day in range(sessions)}
    return harness


@pytest.mark.parametrize(("sessions", "warned"), [(0, True), (60, True), (61, False)])
async def test_a_public_run_says_how_many_of_the_sessions_it_needs_the_archive_holds(sessions: int, warned: bool) -> None:
    harness = public_harness(sessions)

    status = await harness.pipeline.run_full_cycle(built_in_strategy_id="balanced")

    warning = f"The open-data archive holds {sessions} of the 61 sessions needed"
    assert any(error.startswith(warning) for error in status.stats.errors) is warned


async def test_a_personal_run_says_nothing_of_the_archive() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))
    harness.archive.stock_closes = {("2330", date(2026, 10, 16)): rising_history(100.0)[-1]}

    status = await harness.pipeline.run_full_cycle(built_in_strategy_id="balanced")

    assert not any("open-data archive" in error for error in status.stats.errors)


@pytest.mark.parametrize(
    ("audience", "answer"),
    [
        (
            Audience.PUBLIC,
            {"audience": "public", "open_data_only": True, "realtime_quotes": False, "news_articles": False, "mops": False},
        ),
        (
            Audience.PERSONAL,
            {"audience": "personal", "open_data_only": False, "realtime_quotes": True, "news_articles": True, "mops": True},
        ),
    ],
)
async def test_the_web_app_reads_what_the_sites_audience_allows_signed_out(audience: Audience, answer: dict[str, object]) -> None:
    harness = build_harness(config=harness_config().model_copy(update={"audience": audience}))

    async with serve(harness, authorized=False) as client:
        response = await client.get("/v1/market/audience")

    assert (response.status_code, response.json()) == (200, answer)


async def test_the_audience_answer_carries_every_capability_of_the_audience_table() -> None:
    capabilities = {
        name
        for name, member in vars(Audience).items()
        if isinstance(member, property) and isinstance(getattr(Audience.PUBLIC, name), bool)
    }

    assert set(AudienceResponse.model_fields) == {"audience", *capabilities}


async def test_the_market_overview_reads_the_archive_warm_up() -> None:
    harness = public_harness(3)

    async with serve(harness, authorized=False) as client:
        response = await client.get("/v1/market/archive-status")

    assert (response.status_code, response.json()) == (200, {"sessions": 3, "needed": 61})


@pytest.mark.parametrize("path", ["/v1/runs/buzz-scan", "/v1/runs/intraday"])
async def test_the_public_web_api_refuses_buzz_and_intraday_and_still_starts_a_full_cycle(path: str) -> None:
    harness = public_harness(61)
    harness.hold("2330", quantity=1000, average_cost=200.0)

    async with serve(harness) as client:
        refused = await write(client, "POST", path, {})
        runs_after_refusal = dict(harness.journal.runs)
        started = await write(client, "POST", "/v1/runs/full-cycle", {})

    assert (refused.status_code, refused.json()["code"]) == (403, "realtime_quotes_unavailable")
    assert (runs_after_refusal, harness.broker.placed) == ({}, [])
    assert started.status_code == 202


@pytest.fixture
def screen(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    output = io.StringIO()
    monkeypatch.setattr(terminal, "console", Console(file=output, width=250))
    return output


@pytest.mark.parametrize("choice", ["2", "3"])
async def test_the_public_cli_refuses_buzz_and_intraday_before_they_run(choice: str, screen: io.StringIO) -> None:
    harness = public_harness(61)
    harness.hold("2330", quantity=1000, average_cost=200.0)
    harness.discuss("2330", mentions=30, engagement=500)

    assert await harness.answer_menu(choice) is None

    assert "Refused (realtime_quotes_unavailable): audience public uses open data only" in screen.getvalue()
    assert (harness.journal.runs, harness.broker.placed) == ({}, [])


async def test_the_public_cli_analyses_specific_stocks_and_offers_no_manual_buy(screen: io.StringIO) -> None:
    harness = public_harness(61)

    status = await harness.run_menu("4", stock_ids="2330", buy={"2330"})

    assert [stock.stock_id for stock in status.manual_stocks] == ["2330"]
    assert "No manual BUY: audience public has no realtime quote to price one." in screen.getvalue()
    assert (harness.journal.orders, harness.broker.placed) == ({}, [])


async def test_the_personal_cli_still_offers_the_manual_buy(screen: io.StringIO) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)

    await harness.run_menu("4", stock_ids="2330", buy={"2330"})

    assert "No manual BUY" not in screen.getvalue()
    assert [order.stock_id for order in harness.journal.orders.values()] == ["2330"]


def announcement(stock_id: str, subject: str, at: datetime) -> Article:
    """A material information announcement as the open-data archive serves it."""
    return Article(
        stock_id=stock_id,
        source=InformationSource.TWSE_MOPS,
        content_type=ContentType.FACT,
        title=subject,
        content=f"{subject}: details as filed.",
        published_at=at,
        fetched_at=at,
        clause="第51款",
        fact_date=at.date(),
    )


async def test_a_public_ai_step_reads_a_stocks_archived_material_information_and_decides_one_without_any_on_its_technical_score() -> (
    None
):
    harness = public_harness(61)
    harness.list_stock("2317", rising_history(80.0), realtime_price=80.0)
    filed = announcement("2330", "公告本公司董事會通過115年第3季合併財務報告", harness.clock.now() - timedelta(days=1))
    harness.archive.announcements[("2330", filed.published_at)] = filed
    weights = harness.config.analysis

    status = await harness.pipeline.analyse_specific_stocks(["2330", "2317"], built_in_strategy_id="balanced")

    reports = {stock.stock_id: stock for stock in status.manual_stocks}
    [call] = harness.ai.calls
    analysed, unread = reports["2330"], reports["2317"]
    assert (call.stock_id, call.focus) == ("2330", AiAnalysisFocus.FUNDAMENTAL) and filed.title in call.prompt
    assert analysed.ai_report is not None and analysed.technical_score is not None
    assert analysed.composite_score == round(analysed.technical_score * weights.technical_weight + 90 * weights.ai_weight)
    assert unread.ai_report is None and unread.technical_score is not None and unread.composite_score == unread.technical_score
    [note] = [line for line in status.stats.execution_log if "nothing to read" in line]
    assert note.endswith(
        "2317: nothing to read. This site reads no news site, and the open-data archive holds no material information or "
        "TWSE news of it from the last 30 days and no financial report, EPS or monthly revenue of it, so the AI was not "
        "asked: its decision rests on its technical score alone."
    )
    assert (status.stats.failure, status.stats.ai_analysed, harness.news.requested) == (None, 1, [])


async def test_a_personal_ai_step_still_asks_about_a_stock_without_articles() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))

    status = await harness.pipeline.analyse_specific_stocks(["2330"], built_in_strategy_id="balanced")

    assert [call.stock_id for call in harness.ai.calls] == ["2330"] and harness.news.requested == ["2330"]
    assert not any("nothing to read" in line for line in status.stats.execution_log)


async def test_a_public_ai_step_asks_about_a_stock_without_articles_on_its_archived_financials() -> None:
    harness = public_harness(61)
    q3 = QuarterFinancials(quarter=FiscalQuarter(2026, 3), revenue=2763307000.0, eps=47.06)
    harness.archive.held_financials["2330"] = ([q3], [])

    status = await harness.pipeline.analyse_specific_stocks(["2330"], built_in_strategy_id="balanced")

    [call] = harness.ai.calls
    [report] = status.manual_stocks
    assert report.articles == [] and report.ai_report is not None
    assert f"[Financials]\n{q3.describe()}" in call.prompt
    assert not any("nothing to read" in line for line in status.stats.execution_log)


async def test_the_public_web_api_serves_a_stocks_archived_financials_signed_out() -> None:
    harness = public_harness(0)
    q3 = QuarterFinancials(quarter=FiscalQuarter(2026, 3), revenue=21866426.0, gross_profit=None, eps=5.47)
    harness.archive.held_financials["1215"] = ([q3], [])

    async with serve(harness, authorized=False) as client:
        held = await client.get("/v1/market/stocks/1215/financials")
        unheld = await client.get("/v1/market/stocks/9999/financials")

    assert held.status_code == unheld.status_code == 200
    [quarter] = held.json()["quarters"]
    assert (quarter["quarter"], quarter["revenue"], quarter["gross_profit"], quarter["eps"]) == (
        {"year": 2026, "quarter": 3},
        21866426.0,
        None,
        5.47,
    )
    assert unheld.json() == {"stock_id": "9999", "quarters": [], "monthly_revenues": []}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/valuation/market"),
        ("GET", "/v1/valuation/stocks?stock_ids=2330"),
        ("GET", "/v1/valuation/scan?target_pe=15&min_undervaluation=0.1"),
        ("POST", "/v1/valuation/explanation"),
    ],
)
async def test_the_public_web_api_refuses_every_valuation(method: str, path: str) -> None:
    harness = public_harness(61)

    async with serve(harness) as client:
        refused = await client.request(method, path, json={"confirm": True, "stock_id": "2330", "target_pe": 15})

    assert (refused.status_code, refused.json()["code"]) == (403, "mops_unavailable")


@pytest.mark.parametrize("choice", ["5", "6"])
async def test_the_public_cli_refuses_the_valuation_menus_before_they_run(choice: str, screen: io.StringIO) -> None:
    harness = public_harness(61)

    assert await harness.answer_menu(choice) is None

    assert "Refused (mops_unavailable): audience public uses open data only" in screen.getvalue()


async def test_the_attribution_names_each_provider_its_datasets_and_the_license() -> None:
    harness = public_harness(0)

    async with serve(harness, authorized=False) as client:
        response = await client.get("/v1/market/attribution")

    attribution = response.json()
    assert response.status_code == 200
    assert [provider["provider"] for provider in attribution["providers"]] == ["臺灣證券交易所", "證券櫃檯買賣中心"]
    assert "上市公司每日重大訊息" in attribution["providers"][0]["datasets"]
    assert "上櫃股票個股本益比、殖利率、股價淨值比" in attribution["providers"][1]["datasets"]
    assert {"上市公司資產負債表(一般業)", "上市公司綜合損益表(金控業)", "上市公司每月營業收入彙總表", "證交所新聞"} <= set(
        attribution["providers"][0]["datasets"]
    )
    assert {"上櫃公司資產負債表(異業)", "上櫃公司綜合損益表(一般業)", "上櫃公司每月營業收入彙總表"} <= set(
        attribution["providers"][1]["datasets"]
    )
    assert (attribution["license"], attribution["license_url"]) == ("政府資料開放授權條款－第1版", "https://data.gov.tw/license")
