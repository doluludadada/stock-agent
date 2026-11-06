"""
The archive of the TWSE and TPEX open data on a real database of each backend, fed by the real OpenAPI adapter over the
exchanges' trimmed real responses (tests/fixtures): the closes, the material information, the year-to-date EPS, the
valuation ratios, the balance sheets and income statements, the monthly revenue and TWSE's news. Each row is kept under
the date or period its own payload row names, never today, and each financial report as served; saving the same data
again changes nothing, a later report of a session replaces its closes, and a database of this schema version from
before the archive gains its tables at its next start, with no upgrade step. The archive serves its closes as daily
history, its recent material information and the recent TWSE news naming a stock as news, and a stock's quarters and
months as its financials. Then the Web API's timer, over the harness: it archives at the start and again at every
interval, an error included.
"""

import ast
import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import inspect, text
from support.databases import BACKENDS, database_snapshot, empty_database, raw_engine
from support.fakes import RecordingLogger
from support.harness import build_harness, harness_config
from support.settings import shipped_config
from support.web import app_of
from trading_stack import SilentLogger

from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.daily_close_archive import ArchivedMonth, ArchivedQuarter, ArchivedSession
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import (
    ContentType,
    DatabaseBackend,
    FinancialStatement,
    IndustryFormat,
    InformationSource,
    MarketIndex,
    MarketType,
)
from a_domain.types.errors import ListingUnavailableError, RealtimeQuotesUnavailable
from a_domain.types.values import FiscalQuarter
from b_application.config.api_config import ApiConfig
from b_application.config.market_data_config import MarketDataConfig, MarketHoursConfig
from b_application.use_cases.collect.daily_close_archiver import DailyCloseArchiver
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.daily_close_archive import SqlDailyCloseArchive
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock

pytestmark = pytest.mark.asyncio

SOURCES = shipped_config().sources
FIXTURES = Path(__file__).parent / "fixtures"
ARCHIVE_TABLES = (
    "daily_close_archive",
    "index_close_archive",
    "material_information_archive",
    "quarter_eps_archive",
    "valuation_ratio_archive",
    "financial_report_archive",
    "monthly_revenue_archive",
    "exchange_news_archive",
)
NOW = datetime(2026, 11, 6, 18, 0, tzinfo=TAIWAN_TIMEZONE)
"""The evening the new reports' fixtures were saved: their rows name 2026-11-05 (TWSE) and 2026-11-06 (TPEX's ratios)."""

STOCK_ROWS = [
    ("0.2", "28.2", "28.45", "27.7", "twse", "27.85", "2026-10-29", "1101", "31963999"),
    ("-10.0", "2415.0", "2425.0", "2390.0", "twse", "2420.0", "2026-10-29", "2330", "18403916"),
    ("-58.0", "756.0", "779.0", "741.0", "tpex", "775.0", "2026-10-30", "6488", "9849934"),
    ("-4.0", "149.0", "151.0", "147.0", "tpex", "149.5", "2026-10-30", "8069", "6635962"),
]
"""
The listings' stocks that traded, as daily_close_archive holds them (change, close, high, low, market, open,
session_date, stock_id, volume): TWSE's of the session 2026-10-29 and TPEX's of 2026-10-30, as each listing dates them.
"""

INDEX_ROWS = [
    ("-1374.19", "41574.72", "twse", "2026-11-05"),
    ("-1.02", "369.24", "tpex", "2026-11-02"),
    ("-23.72", "345.52", "tpex", "2026-11-03"),
    ("-2.02", "343.5", "tpex", "2026-11-04"),
    ("-22.03", "321.47", "tpex", "2026-11-05"),
    ("-17.45", "304.02", "tpex", "2026-11-06"),
]
"""The TAIEX of MI_INDEX's one session and the TPEx Index of tpex_index's five, as index_close_archive holds them."""

FACT_DATES = {"2886": "2026-11-04", "4935": "2026-11-05", "3526": "2026-11-05", "3131": "2026-11-05"}
"""The fact date of each fixture announcement: 1151104 or 1151105 in the ROC calendar."""


def served_announcements() -> list[tuple[str, str, str, str]]:
    """
    Each fixture announcement's (clause, description, fact_date, stock_id) as material_information_archive must hold
    it: the clause and the text exactly as t187ap04_L's three rows and mopsfin_t187ap04_O's two serve them.
    """
    served = [("twse_t187ap04_l.json", "公司代號"), ("tpex_mopsfin_t187ap04_o.json", "SecuritiesCompanyCode")]
    rows = [(row, row[field]) for file, field in served for row in json.loads((FIXTURES / file).read_text(encoding="utf-8"))]
    return sorted((row["符合條款"], row["說明"], FACT_DATES[stock_id], stock_id) for row, stock_id in rows)


EPS_ROWS = [
    ("8.03", "3", "1232", "2026"),
    ("5.47", "3", "1215", "2026"),
    ("11.2", "3", "1268", "2026"),
    ("-0.21", "3", "1796", "2026"),
]
"""Each company's (eps, quarter, stock_id, year) of ROC 115 Q3 as quarter_eps_archive holds them: the EPS as served."""

RATIO_ROWS = [
    ("2.94", "0.88", "None", "2026-11-05", "1101"),
    ("0.98", "9.03", "25.96", "2026-11-05", "2330"),
    ("0.94", "1.57", "9.93", "2026-11-06", "1240"),
    ("1.5", "1.85", "28.83", "2026-11-06", "6488"),
]
"""
Each stock's (dividend_yield, pb_ratio, pe_ratio, session_date, stock_id) as valuation_ratio_archive holds them: BWIBBU_ALL
dates its session 2026-11-05 and tpex_mainboard_peratio_analysis 2026-11-06. TWSE leaves 1101's P/E blank.
"""


def archived_on(
    day: date, stocks: int = 0, indexes: int = 0, ratios: int = 0, announcements: int = 0, news: int = 0
) -> ArchivedSession:
    return ArchivedSession(
        session_date=day,
        stocks=stocks,
        indexes=indexes,
        valuation_ratios=ratios,
        material_information=announcements,
        exchange_news=news,
    )


SESSIONS = [
    archived_on(date(2026, 3, 17), news=1),
    archived_on(date(2026, 9, 23), news=1),
    archived_on(date(2026, 10, 19), news=1),
    archived_on(date(2026, 10, 29), stocks=2),
    archived_on(date(2026, 10, 30), stocks=2),
    archived_on(date(2026, 11, 2), indexes=1),
    archived_on(date(2026, 11, 3), indexes=1),
    archived_on(date(2026, 11, 4), indexes=1),
    archived_on(date(2026, 11, 5), indexes=2, ratios=2, announcements=5, news=3),
    archived_on(date(2026, 11, 6), indexes=1, ratios=2),
]
"""
The dates each report's rows name: 2886 announced at 06:56 Taipei time on 2026-11-05, which is still 2026-11-04 in UTC,
so the announcements count under the Taipei date. The news list's six items are dated from 2026-03-17 to 2026-11-05.
"""

QUARTERS = [ArchivedQuarter(quarter=FiscalQuarter(2026, 3), eps=4, balance_sheets=6, income_statements=6)]
"""
ROC 115 Q3: four companies' EPS, and the statements of TWSE's 1215 and 1232 and TPEX's 1268 and 1796 (general format)
and 6023 and 6026 (securities). TWSE's bank balance sheets serve one row with only its date, which names no company.
"""

MONTHS = [ArchivedMonth(year=2026, month=9, companies=5)]
"""ROC 11509: TWSE's 1101, 1215 and 2330 and TPEX's 1240 and 1268."""

REPORTS = SOURCES.exchange.financial_reports.urls
FINANCIAL_REPORT_FILES = {
    REPORTS[MarketType.TWSE][FinancialStatement.BALANCE_SHEET][IndustryFormat.GENERAL]: "twse_t187ap07_l_ci.json",
    REPORTS[MarketType.TWSE][FinancialStatement.INCOME_STATEMENT][IndustryFormat.GENERAL]: "twse_t187ap06_l_ci.json",
    REPORTS[MarketType.TWSE][FinancialStatement.BALANCE_SHEET][IndustryFormat.BANK]: "twse_t187ap07_l_basi.json",
    REPORTS[MarketType.TPEX][FinancialStatement.BALANCE_SHEET][IndustryFormat.GENERAL]: "tpex_mopsfin_t187ap07_o_ci.json",
    REPORTS[MarketType.TPEX][FinancialStatement.INCOME_STATEMENT][IndustryFormat.GENERAL]: "tpex_mopsfin_t187ap06_o_ci.json",
    REPORTS[MarketType.TPEX][FinancialStatement.BALANCE_SHEET][IndustryFormat.SECURITIES]: "tpex_mopsfin_t187ap07_o_bd.json",
    REPORTS[MarketType.TPEX][FinancialStatement.INCOME_STATEMENT][IndustryFormat.SECURITIES]: "tpex_mopsfin_t187ap06_o_bd.json",
}
"""The reports the fixtures hold; the other seventeen answer 503, as a report that fails to load."""


OPENAPI_FILES = {
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
    SOURCES.exchange.monthly_revenue[MarketType.TWSE].url: "twse_t187ap05_l.json",
    SOURCES.exchange.monthly_revenue[MarketType.TPEX].url: "tpex_mopsfin_t187ap05_o.json",
    SOURCES.exchange.exchange_news.url: "twse_news_newslist.json",
    **FINANCIAL_REPORT_FILES,
}
"""Every OpenAPI endpoint the archive reads, and the file of its trimmed real answer saved on the evening of NOW."""


@pytest.fixture
def payloads(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, str]]]:
    """
    What the OpenAPI endpoints answer, which a test may change before a run; an endpoint left out answers 503. The
    market clock reads NOW.
    """
    answers = {url: json.loads((FIXTURES / name).read_text(encoding="utf-8")) for url, name in OPENAPI_FILES.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        rows = answers.get(str(request.url))
        return httpx.Response(503) if rows is None else httpx.Response(200, json=rows)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(TaiwanMarketClock, "now", lambda clock: NOW)
    return answers


def sql_archive(connector: DatabaseConnector, logger: ILoggingProvider | None = None) -> SqlDailyCloseArchive:
    clock = TaiwanMarketClock(MarketHoursConfig())
    days = shipped_config().analysis.material_information_days
    return SqlDailyCloseArchive(connector, clock, SOURCES.exchange, days, logger or SilentLogger())


async def archive_run(
    connector: DatabaseConnector, logger: ILoggingProvider | None = None
) -> tuple[list[ArchivedSession], list[ArchivedQuarter], list[ArchivedMonth]]:
    """One run of the archive with a fresh download of every endpoint, as `just archive-closes` starts it."""
    clock = TaiwanMarketClock(MarketHoursConfig())
    provider = TaiwanStockProvider(SOURCES.exchange, clock, MarketDataConfig(), SilentLogger())
    return await DailyCloseArchiver(provider, sql_archive(connector, logger), SilentLogger()).execute()


async def started_database(backend: DatabaseBackend, folder: Path) -> DatabaseConnector:
    connector = await empty_database(backend, folder)
    await connector.init_db()
    return connector


@pytest.mark.parametrize("backend", BACKENDS)
async def test_each_row_is_kept_under_the_date_or_period_its_own_payload_row_names(
    backend: DatabaseBackend, tmp_path: Path, payloads: dict[str, list[dict[str, str]]]
) -> None:
    connector = await started_database(backend, tmp_path)

    try:
        sessions, quarters, months = await archive_run(connector)
    finally:
        await connector.close()

    archived = await database_snapshot(backend, tmp_path)
    columns, announcements = archived["material_information_archive"]
    kept = [columns.index(name) for name in ("clause", "description", "fact_date", "stock_id")]
    assert (sessions, quarters, months) == (SESSIONS, QUARTERS, MONTHS)
    assert archived["daily_close_archive"][1] == sorted(STOCK_ROWS)
    assert archived["index_close_archive"][1] == sorted(INDEX_ROWS)
    assert sorted(tuple(row[index] for index in kept) for row in announcements) == served_announcements()
    assert archived["quarter_eps_archive"][1] == sorted(EPS_ROWS)
    assert archived["valuation_ratio_archive"][1] == sorted(RATIO_ROWS)
    assert archived_reports(archived) == served_reports()
    assert len(archived["monthly_revenue_archive"][1]) == 5
    assert sorted(row[2] for row in archived["exchange_news_archive"][1]) == sorted(
        row["Url"] for row in json.loads((FIXTURES / "twse_news_newslist.json").read_text(encoding="utf-8"))
    )
    assert archived["ohlcv_data"][1] == []


def served_reports() -> list[tuple[str, str, str, str, str, str, str, dict[str, str]]]:
    """
    Each fixture report row that names a company, as financial_report_archive must hold it: (stock_id, year, quarter,
    statement, market, industry_format, served_date, items), its items every field of the row but the five that say
    which company, period and day it is of, as served.
    """
    identity = SOURCES.exchange.financial_reports.identity
    kinds = {
        url: (market, statement, kind)
        for market, by_statement in REPORTS.items()
        for statement, by_kind in by_statement.items()
        for kind, url in by_kind.items()
    }
    rows = []

    for url, name in FINANCIAL_REPORT_FILES.items():
        market, statement, kind = kinds[url]

        for row in json.loads((FIXTURES / name).read_text(encoding="utf-8")):
            if code := row.get("公司代號") or row.get("SecuritiesCompanyCode"):
                items = {field: value for field, value in row.items() if field not in identity}
                rows.append((code, "2026", "3", statement.value, market.value, kind.value, "2026-11-06", items))

    return sorted(rows, key=str)


def archived_reports(archived: dict[str, tuple[list[str], list[tuple[str, ...]]]]) -> list[tuple[str, ...]]:
    """
    financial_report_archive's rows in the order of served_reports, each one's items read back: SQLite hands the JSON
    column over as its text and PostgreSQL as the object's repr, and both are a Python literal of the served strings.
    """
    columns, rows = archived["financial_report_archive"]
    names = ("stock_id", "year", "quarter", "statement", "market", "industry_format", "served_date")
    return sorted(
        ((*(row[columns.index(name)] for name in names), ast.literal_eval(row[columns.index("items")])) for row in rows), key=str
    )


@pytest.mark.parametrize("backend", BACKENDS)
async def test_the_archive_serves_a_stocks_material_information_of_the_window_as_news_newest_first_and_as_served(
    backend: DatabaseBackend, tmp_path: Path, payloads: dict[str, list[dict[str, str]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = await started_database(backend, tmp_path)
    archive = sql_archive(connector)
    subjects = {row["發言時間"]: row["主旨 "] for row in payloads[SOURCES.exchange.material_information[MarketType.TWSE].url]}

    try:
        await archive_run(connector)
        news = await archive.fetch_news("4935")
        monkeypatch.setattr(TaiwanMarketClock, "now", lambda clock: NOW + timedelta(days=31))
        a_month_later = await archive.fetch_news("4935")
    finally:
        await connector.close()

    assert [(article.published_at, article.title) for article in news] == [
        (taipei(date(2026, 11, 5), time(16, 33, 16)), subjects["163316"]),
        (taipei(date(2026, 11, 5), time(16, 32, 49)), subjects["163249"]),
    ]
    assert "\r\n" in news[0].title and news[0].title.startswith("代重要子公司Solid State Technology Limited公告")
    assert {(article.source, article.content_type, article.clause, article.fact_date) for article in news} == {
        (InformationSource.TWSE_MOPS, ContentType.FACT, "第14款", date(2026, 11, 5))
    }
    assert a_month_later == []


@pytest.mark.parametrize("backend", BACKENDS)
async def test_the_archive_serves_the_twse_news_naming_a_stock_of_the_window_with_its_material_information_newest_first(
    backend: DatabaseBackend, tmp_path: Path, payloads: dict[str, list[dict[str, str]]]
) -> None:
    connector = await started_database(backend, tmp_path)
    archive = sql_archive(connector)
    filed = {row["發言時間"]: row["主旨 "] for row in payloads[SOURCES.exchange.material_information[MarketType.TWSE].url]}
    penalty = {
        "Title": "臺灣證券交易所針對茂林-KY（證券代號：4935）違反重大訊息規定，處以違約金",
        "Url": "https://www.twse.com.tw/n/4935",
        "Date": "1151106",
    }
    payloads[SOURCES.exchange.exchange_news.url].append(penalty)

    try:
        await archive_run(connector)
        news = {stock_id: await archive.fetch_news(stock_id) for stock_id in ("4935", "7848", "0053", "6825", "6604", "2330")}
    finally:
        await connector.close()

    assert [(article.source, article.published_at, article.title) for article in news["4935"]] == [
        (InformationSource.TWSE_NEWS, taipei(date(2026, 11, 6)), penalty["Title"]),
        (InformationSource.TWSE_MOPS, taipei(date(2026, 11, 5), time(16, 33, 16)), filed["163316"]),
        (InformationSource.TWSE_MOPS, taipei(date(2026, 11, 5), time(16, 32, 49)), filed["163249"]),
    ]
    assert [(article.stock_id, article.url, article.content_type) for article in news["4935"][:1]] == [
        ("4935", penalty["Url"], ContentType.NEWS)
    ]
    assert [article.title for article in news["7848"]] == ["騏億鑫(證券代號：7848)採競價拍賣方式辦理承銷，於11月5日順利完成"]
    assert [article.title for article in news["0053"]] == ["元大科技市值ETF(0053)將進行分割作業，115年12月8日為新受益憑證上市買賣日"]
    assert [article.published_at for article in news["6825"]] == [taipei(date(2026, 10, 19))]
    assert (news["6604"], news["2330"]) == ([], [])


@pytest.mark.parametrize("backend", BACKENDS)
async def test_the_archive_reads_a_stocks_financials_by_its_industry_formats_columns_with_its_eps_and_monthly_revenue(
    backend: DatabaseBackend, tmp_path: Path, payloads: dict[str, list[dict[str, str]]]
) -> None:
    connector = await started_database(backend, tmp_path)
    archive = sql_archive(connector)

    for statement in FinancialStatement:
        tpex_general = payloads[REPORTS[MarketType.TPEX][statement][IndustryFormat.GENERAL]]
        tpex_general[:] = [row for row in tpex_general if row["SecuritiesCompanyCode"] != "1268"]

    try:
        await archive_run(connector)
        financials = {stock_id: await archive.financials(stock_id) for stock_id in ("1215", "6023", "1268", "2330", "9999")}
    finally:
        await connector.close()

    q3 = FiscalQuarter(2026, 3)
    assert financials["1215"][0] == [
        QuarterFinancials(
            quarter=q3,
            revenue=21866426.0,
            gross_profit=4063514.0,
            operating_income=2149648.0,
            net_income=1612807.0,
            eps=5.47,
            total_assets=34472391.0,
            total_liabilities=22263677.0,
            equity=11763790.0,
            book_value_per_share=39.91,
        )
    ]
    assert financials["6023"] == (
        [
            QuarterFinancials(
                quarter=q3,
                revenue=3650123.0,
                operating_income=-715300.0,
                net_income=2622548.0,
                total_assets=351172262.0,
                total_liabilities=323852905.0,
                equity=27319357.0,
                book_value_per_share=60.98,
            )
        ],
        [],
    )
    assert financials["2330"] == (
        [],
        [
            MonthlyRevenue(
                stock_id="2330",
                year=2026,
                month=9,
                market=MarketType.TWSE,
                served_date=date(2026, 10, 17),
                company_name="台積電",
                industry="半導體業",
                revenue=511857399.0,
                previous_month_revenue=514805337.0,
                last_year_revenue=330980920.0,
                month_over_month_percent=-0.5726315925897248,
                year_over_year_percent=54.64861207105231,
                cumulative_revenue=3898726974.0,
                last_year_cumulative_revenue=2762963851.0,
                cumulative_year_over_year_percent=41.106694993093484,
                note="因先進製程產品需求增加所致。",
            )
        ],
    )
    assert [revenue.period_label for revenue in financials["1215"][1]] == ["2026-09"]
    assert financials["1268"][0] == [QuarterFinancials(quarter=q3, eps=11.2)]
    assert financials["9999"] == ([], [])


@pytest.mark.parametrize("backend", BACKENDS)
async def test_archiving_the_same_sessions_again_changes_nothing(
    backend: DatabaseBackend, tmp_path: Path, payloads: dict[str, list[dict[str, str]]]
) -> None:
    connector = await started_database(backend, tmp_path)

    try:
        first = await archive_run(connector)
        archived = await database_snapshot(backend, tmp_path)
        second = await archive_run(connector)
    finally:
        await connector.close()

    assert first == second == (SESSIONS, QUARTERS, MONTHS)
    assert await database_snapshot(backend, tmp_path) == archived


REFUSED_ANNOUNCEMENTS = {
    DatabaseBackend.SQLITE: [
        "CREATE TRIGGER refuse_announcements BEFORE INSERT ON material_information_archive "
        "BEGIN SELECT RAISE(ABORT, 'refused by the test'); END"
    ],
    DatabaseBackend.POSTGRESQL: [
        "CREATE FUNCTION refuse_insert() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'refused by the test'; END $$",
        "CREATE TRIGGER refuse_announcements BEFORE INSERT ON material_information_archive "
        "FOR EACH ROW EXECUTE FUNCTION refuse_insert()",
    ],
}
"""A trigger on each backend that makes the database refuse every row of material_information_archive."""


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_table_the_database_refuses_is_logged_by_name_and_every_other_table_is_still_saved(
    backend: DatabaseBackend, tmp_path: Path, payloads: dict[str, list[dict[str, str]]]
) -> None:
    connector = await started_database(backend, tmp_path)
    engine = raw_engine(backend, tmp_path)

    async with engine.begin() as connection:
        for statement in REFUSED_ANNOUNCEMENTS[backend]:
            await connection.execute(text(statement))

    await engine.dispose()
    logger = RecordingLogger()

    try:
        sessions, quarters, months = await archive_run(connector, logger)
    finally:
        await connector.close()

    archived = await database_snapshot(backend, tmp_path)
    [error] = [message for level, message in logger.records if level == "error"]
    assert "material_information_archive" in error and "refused by the test" in error
    assert archived["material_information_archive"][1] == []
    assert archived["daily_close_archive"][1] == sorted(STOCK_ROWS)
    assert archived["index_close_archive"][1] == sorted(INDEX_ROWS)
    assert sessions == [replace(held, material_information=0) for held in SESSIONS]
    assert (quarters, months) == (QUARTERS, MONTHS)


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_nul_character_the_exchange_serves_in_a_text_is_archived_without_it(
    backend: DatabaseBackend, tmp_path: Path, payloads: dict[str, list[dict[str, str]]]
) -> None:
    connector = await started_database(backend, tmp_path)
    announcement = payloads[SOURCES.exchange.material_information[MarketType.TWSE].url][0]
    announcement["說明"] = announcement["說明"][:4] + "\x00" + announcement["說明"][4:]

    try:
        sessions, _, _ = await archive_run(connector)
    finally:
        await connector.close()

    columns, announcements = (await database_snapshot(backend, tmp_path))["material_information_archive"]
    kept = [columns.index(name) for name in ("clause", "description", "fact_date", "stock_id")]
    assert sorted(tuple(row[index] for index in kept) for row in announcements) == served_announcements()
    assert sessions == SESSIONS


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_started_database_indexes_the_session_dates_of_the_archived_closes(backend: DatabaseBackend, tmp_path: Path) -> None:
    connector = await started_database(backend, tmp_path)
    await connector.close()
    engine = raw_engine(backend, tmp_path)

    async with engine.connect() as connection:
        indexes = await connection.run_sync(lambda sync: inspect(sync).get_indexes("daily_close_archive"))

    await engine.dispose()
    assert ["session_date"] in [index["column_names"] for index in indexes]


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_later_report_of_a_session_replaces_its_closes(
    backend: DatabaseBackend, tmp_path: Path, payloads: dict[str, list[dict[str, str]]]
) -> None:
    connector = await started_database(backend, tmp_path)
    tsmc = next(row for row in payloads[SOURCES.exchange.twse_daily_quotes_url] if row["Code"] == "2330")
    taiex = next(row for row in payloads[SOURCES.exchange.twse_index_url] if row["指數"] == "發行量加權股價指數")

    try:
        await archive_run(connector)
        tsmc["ClosingPrice"], taiex["收盤指數"] = "2400.00", "41600.00"
        sessions, _, _ = await archive_run(connector)
    finally:
        await connector.close()

    archived = await database_snapshot(backend, tmp_path)
    stocks = {row[7]: row[1] for row in archived["daily_close_archive"][1]}
    indexes = {(row[2], row[3]): row[1] for row in archived["index_close_archive"][1]}
    assert sessions == SESSIONS
    assert (stocks["2330"], stocks["1101"]) == ("2400.0", "28.2")
    assert (indexes["twse", "2026-11-05"], indexes["tpex", "2026-11-05"]) == ("41600.0", "321.47")


@pytest.mark.parametrize("backend", BACKENDS)
async def test_with_every_endpoint_down_the_run_is_refused_and_saves_nothing(
    backend: DatabaseBackend, tmp_path: Path, payloads: dict[str, list[dict[str, str]]]
) -> None:
    connector = await started_database(backend, tmp_path)
    payloads.clear()

    try:
        with pytest.raises(ListingUnavailableError):
            await archive_run(connector)
    finally:
        await connector.close()

    archived = await database_snapshot(backend, tmp_path)
    assert [archived[table][1] for table in ARCHIVE_TABLES] == [[]] * len(ARCHIVE_TABLES)


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_database_of_this_schema_version_without_the_archive_gains_it_at_its_next_start(
    backend: DatabaseBackend, tmp_path: Path, payloads: dict[str, list[dict[str, str]]]
) -> None:
    connector = await started_database(backend, tmp_path)
    engine = raw_engine(backend, tmp_path)

    async with engine.begin() as connection:
        for table in ARCHIVE_TABLES:
            await connection.execute(text(f"DROP TABLE {table}"))

        await connection.execute(
            text(
                "INSERT INTO technical_settings (owner_id, active_strategy_id, buzz_strategy_id, revision) "
                "VALUES ('local', 'trend', 'buzz', 4)"
            )
        )

    await engine.dispose()
    before = await database_snapshot(backend, tmp_path)

    try:
        state = await connector.state()
        await connector.init_db()
        held = await archive_run(connector)
    finally:
        await connector.close()

    after = await database_snapshot(backend, tmp_path)
    assert (state.refusal, state.pending) == (None, ())
    assert sorted(set(after) - set(before)) == sorted(ARCHIVE_TABLES)
    assert {table: dump for table, dump in after.items() if table in before} == before
    assert held == (SESSIONS, QUARTERS, MONTHS)


def taipei(day: date, at: time = time(13, 30)) -> datetime:
    return datetime.combine(day, at, TAIWAN_TIMEZONE)


@pytest.mark.parametrize("backend", BACKENDS)
async def test_the_archive_serves_its_stock_and_index_closes_as_daily_history_and_never_a_realtime_quote(
    backend: DatabaseBackend, tmp_path: Path, payloads: dict[str, list[dict[str, str]]]
) -> None:
    connector = await started_database(backend, tmp_path)
    archive = sql_archive(connector)
    stocks = [Stock(stock_id=stock_id) for stock_id in ("2330", "6488", "9999")]
    until_the_6th = taipei(date(2026, 11, 6), time.max)

    try:
        await archive_run(connector)
        session_count = await archive.session_count()
        october = await archive.fetch_history(stocks, taipei(date(2026, 10, 1), time.min), until_the_6th)
        from_the_30th = await archive.fetch_history(stocks, taipei(date(2026, 10, 30), time.min), until_the_6th)
        taiex = await archive.fetch_index_history(MarketIndex.TAIEX, taipei(date(2026, 10, 1), time.min), until_the_6th)

        with pytest.raises(RealtimeQuotesUnavailable):
            await archive.fetch_realtime_bars(stocks)
    finally:
        await connector.close()

    assert session_count == sum(1 for session in SESSIONS if session.stocks) == 2
    assert {stock_id: [(bar.ts, bar.open, bar.close, bar.volume) for bar in bars] for stock_id, bars in october.items()} == {
        "2330": [(taipei(date(2026, 10, 29)), 2420.0, 2415.0, 18403916)],
        "6488": [(taipei(date(2026, 10, 30)), 775.0, 756.0, 9849934)],
    }
    assert list(from_the_30th) == ["6488"]
    assert [(bar.ts, bar.open, bar.high, bar.low, bar.close, bar.change) for bar in taiex] == [
        (taipei(date(2026, 11, 5)), 41574.72, 41574.72, 41574.72, 41574.72, -1374.19)
    ]


async def until(condition: Callable[[], bool]) -> None:
    for _ in range(300):
        if condition():
            return

        await asyncio.sleep(0.01)

    raise AssertionError("the condition did not hold within 3 seconds")


async def test_the_web_api_archives_the_closes_at_its_start() -> None:
    harness = build_harness()
    session_close = harness.clock.session_close(date(2026, 11, 5))
    harness.stocks.stocks = {"2330": Stock(stock_id="2330", market=MarketType.TWSE)}
    harness.stocks.closes = {"2330": Ohlcv(ts=session_close, open=2420, high=2425, low=2390, close=2415, volume=18403916)}
    harness.stocks.index_closes = {MarketType.TWSE: [Ohlcv(ts=session_close, close=41574.72, change=-1374.19)]}

    async with app_of(harness):
        await until(lambda: harness.archive.saves == 1)

    assert harness.config.api.archive_interval_hours == 3
    assert await harness.archive.sessions() == [archived_on(date(2026, 11, 5), stocks=1, indexes=1)]


async def test_the_web_api_archives_again_at_every_interval_after_a_run_that_failed() -> None:
    harness = build_harness(config=harness_config().model_copy(update={"api": ApiConfig(archive_interval_hours=0.02 / 3600)}))
    session_close = harness.clock.session_close(date(2026, 11, 6))

    async with app_of(harness):
        await until(lambda: any("could not be archived" in message for level, message in harness.logger.records if level == "error"))
        harness.stocks.index_closes = {MarketType.TPEX: [Ohlcv(ts=session_close, close=304.02, change=-17.45)]}
        await until(lambda: harness.archive.saves >= 2)

    assert await harness.archive.sessions() == [archived_on(date(2026, 11, 6), indexes=1)]


@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_company_without_subsidiaries_reads_its_net_income_and_equity_from_its_totals(
    backend: DatabaseBackend, tmp_path: Path, payloads: dict[str, list[dict[str, str]]]
) -> None:
    connector = await started_database(backend, tmp_path)
    archive = sql_archive(connector)
    split_columns = ("淨利（淨損）歸屬於母公司業主", "淨利（淨損）歸屬於非控制權益", "歸屬於母公司業主之權益合計", "非控制權益")

    for statement in FinancialStatement:
        for row in payloads[REPORTS[MarketType.TWSE][statement][IndustryFormat.GENERAL]]:
            if row["公司代號"] == "1215":
                row.update({column: "" for column in split_columns if column in row})

    try:
        await archive_run(connector)
        [quarter], _ = await archive.financials("1215")
    finally:
        await connector.close()

    assert (quarter.net_income, quarter.equity) == (1639340.0, 12208714.0)
