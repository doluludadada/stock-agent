"""
A company's shareholders'-meeting annual report: located on the exchange's document site in three paced requests, its
text read by a worker process, and its sections kept as text in the article store, by a personal site alone.
"""

import asyncio
import sys
import tempfile
import time
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject
from support.fakes import FakeAnnualReportProvider, FakeArticleStore, FakeCompanyProfileRepository
from support.settings import shipped_config
from trading_stack import MovableClock, SilentLogger

from a_domain.model.market.article import Article
from a_domain.model.market.company_profile import CompanyProfile
from a_domain.ports.market.annual_report_provider import AnnualReport
from a_domain.rules.collect.company_background import AnnualReportDueRule
from a_domain.types.enums import AnnualReportSection, Audience, ContentType, InformationSource
from b_application.use_cases.collect.annual_report_refresh import AnnualReportRefresh
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.article_store import SqlArticleStore
from c_infrastructure.market import annual_report_text, request_pace
from c_infrastructure.market.annual_report_text import readable_text, report_sections, section_windows
from c_infrastructure.market.request_pace import RequestPace
from c_infrastructure.market.twse_annual_report_provider import TwseAnnualReportProvider
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE
from d_presentation.dependencies import create_annual_report_provider

pytestmark = pytest.mark.asyncio

CONFIG = shipped_config()
REPORTS = CONFIG.sources.annual_reports
FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 15, 10, 0, tzinfo=TAIWAN_TIMEZONE)
PATTERNS = {section.value: patterns for section, patterns in REPORTS.section_patterns.items()}
LATIN = {
    AnnualReportSection.BUSINESS_SCOPE: ["Business scope"],
    AnnualReportSection.PRODUCT_MIX: ["Product mix"],
    AnnualReportSection.MAJOR_CUSTOMERS: ["Customers of 10%"],
}
"""Marks a PDF written with a standard font can hold: the test's own reports are in Latin letters."""

LATIN_REPORTS = REPORTS.model_copy(update={"section_patterns": LATIN, "min_text_length": 50, "contents_share": 0.0})
LINES = [
    "Annual report 2025",
    "Business scope: control systems integration for refineries and plants.",
    "Product mix: system integration 17.31%, construction 80.65%, sales 2.04%.",
    "Customers of 10% or more: CTCI 58.12%, CPC 13.61%.",
]


def write_pdf(path: Path, lines: list[str], encrypted: bool = False) -> Path:
    """A one-page PDF whose page writes `lines` in Helvetica; encrypted with AES-256 and no user password when asked."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    content = StreamObject()
    content.set_data(("BT /F1 11 Tf 40 800 Td " + " ".join(f"({line}) Tj 0 -16 Td" for line in lines) + " ET").encode())
    fonts = DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): fonts})
    page[NameObject("/Contents")] = writer._add_object(content)

    if encrypted:
        writer.encrypt(user_password="", owner_password="owner", algorithm="AES-256")

    writer.write(path)
    return path


def read(path: Path) -> dict[str, str] | None:
    request = LATIN_REPORTS.reader_request()
    request.pop("memory_mb")
    request.pop("cpu_seconds")

    with path.open("rb") as report:
        return report_sections(report, **request)  # type: ignore[arg-type]


LEADERS = {"leader_pattern": REPORTS.contents_leader_pattern, "leader_reach": REPORTS.contents_leader_reach}


# ------------------------------------------------ the report's text ------------------------------------------------ #


async def test_a_section_starts_at_its_first_mark_past_the_table_of_contents() -> None:
    contents = "目錄 一、業務內容 營業比重 .............. 78 二、從業員工 ...... 95 "
    filler = "致股東報告書。" * 200
    scope = "肆、營運概況 (一)業務範圍 1.所營業務之主要內容: 控制系統整合。 "
    body = scope + "2.營業比重: 系統整合收入 17.31% 工程建造收入 80.65%。 三、從業員工 173 人。"
    text = contents + filler + body

    windows = section_windows(text, PATTERNS, lead=10, length=30, contents_share=0.0, **LEADERS)

    assert sorted(windows) == ["business_scope", "employees", "product_mix"]
    assert windows["product_mix"].startswith("控制系統整合。 2.營業比重: 系統整合收入 17.31%")
    assert "所營業務之主要內容: 控制系統整合" in windows["business_scope"]
    assert len(windows["employees"]) <= 40 and "從業員工 173 人" in windows["employees"]


async def test_a_mark_within_the_first_share_of_the_text_is_the_table_of_contents() -> None:
    text = "四、從業員工資訊 95 五、環保支出 96 " + "營運概況。" * 300 + "4.3 從業員工資訊 員工人數 173"

    windows = section_windows(text, {"employees": PATTERNS["employees"]}, lead=0, length=20, contents_share=0.05, **LEADERS)

    assert windows == {"employees": "從業員工資訊 員工人數 173"}


@pytest.mark.parametrize(
    "heading",
    [
        "A. 占銷貨總額百分之十以上之銷貨客戶",
        "2.最近二年度占銷貨總額 10%以上客戶",
        "最近二年度任一年度中曾占進(銷)貨總額百分之十以上之客戶名稱",
        "2.最近二年度銷貨客戶",
        "1. 最近二年度占進貨總額 10%以上廠商",
    ],
)
async def test_the_customers_section_is_found_under_each_heading_the_reports_use(heading: str) -> None:
    text = "其他內容。" * 50 + heading + " 名稱 金額 比率 甲公司 58.12"

    assert "甲公司 58.12" in section_windows(text, PATTERNS, lead=0, length=60, contents_share=0.0, **LEADERS)["major_customers"]


async def test_a_wrapped_word_is_joined_and_compatibility_characters_become_ordinary() -> None:
    assert readable_text("台灣中油股\n份有限公司　１３．６１％\n（關係企業）\n\n ABC") == "台灣中油股份有限公司 13.61% (關係企業) ABC"


async def test_a_report_s_sections_are_read_from_its_pages(tmp_path: Path) -> None:
    sections = read(write_pdf(tmp_path / "plain.pdf", LINES))

    assert sections is not None and sorted(sections) == ["business_scope", "major_customers", "product_mix"]
    assert "Product mix: system integration 17.31%" in sections["product_mix"]


async def test_a_report_encrypted_without_a_password_is_read_like_any_other(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "encrypted.pdf", LINES, encrypted=True)

    assert b"/Encrypt" in path.read_bytes()
    assert read(path) == read(write_pdf(tmp_path / "plain.pdf", LINES))


async def test_a_report_with_no_text_has_no_section_and_a_file_that_is_no_pdf_is_none(tmp_path: Path) -> None:
    scanned = write_pdf(tmp_path / "scanned.pdf", [])
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"<html>503 Service Unavailable</html>")

    assert read(scanned) == {}
    assert read(broken) is None


# ------------------------------------------------ the document site ------------------------------------------------ #


class DocumentSite:
    """The exchange's document site as the fixtures saved it for 5209, serving `pdf` as the file; `sent` is every request."""

    def __init__(self, pdf: bytes, folder: Path) -> None:
        self.pdf = pdf
        self.folder = folder
        self.sent: list[httpx.Request] = []
        self.refuse_file = False

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)

        if request.method == "GET" and request.url.path == "/server-java/t57sb01":
            listed = request.url.params["co_id"] == "5209" and request.url.params["year"] == "114"
            page = (FIXTURES / "doc_twse_t57sb01_index_5209.html").read_bytes()
            return httpx.Response(200, content=page if listed else page.split(b"<table border='5'")[0])

        if request.method == "POST":
            return httpx.Response(200, content=(FIXTURES / "doc_twse_t57sb01_file_5209.html").read_bytes())

        if self.refuse_file:
            raise httpx.ConnectError("Connection refused")

        return httpx.Response(200, content=self.pdf)


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> DocumentSite:
    document_site = DocumentSite(write_pdf(tmp_path / "served.pdf", LINES, encrypted=True).read_bytes(), tmp_path)
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(document_site.answer)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
    return document_site


@pytest.fixture(autouse=True)
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """How long each request waited for its turn: the pace sleeps here instead of on the clock, in every test."""
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(request_pace.asyncio, "sleep", sleep)
    return slept


def provider(reports=LATIN_REPORTS) -> TwseAnnualReportProvider:
    return TwseAnnualReportProvider(reports, RequestPace(), MovableClock(NOW), SilentLogger())


async def test_a_report_is_three_paced_requests_and_its_sections_are_articles_under_the_listing_page(
    site: DocumentSite, waits: list[float]
) -> None:
    report = await provider().fetch("5209", 2024)

    index_url = REPORTS.index_url.format(stock_id="5209", roc_year=114)
    assert [(request.method, str(request.url)) for request in site.sent] == [
        ("GET", index_url),
        ("POST", REPORTS.file_url),
        ("GET", f"{REPORTS.site_url}/pdf/2024_5209_20250528F04_20261114_200410.pdf"),
    ]
    assert site.sent[1].content == b"step=9&kind=F&co_id=5209&filename=2024_5209_20250528F04.pdf"
    assert len(waits) == 2 and all(REPORTS.request_interval_seconds - 1 < wait <= REPORTS.request_interval_seconds for wait in waits)
    assert all(request.headers["user-agent"].startswith("Mozilla/5.0") for request in site.sent)
    assert report is not None and (report.fiscal_year, report.file) == (2024, "2024_5209_20250528F04.pdf")
    mix = next(section for section in report.sections if section.url == f"{index_url}#product_mix")
    assert (mix.source, mix.content_type, mix.stock_id) == (InformationSource.ANNUAL_REPORT, ContentType.REPORT, "5209")
    assert mix.title == "113年度股東會年報：主要產品及營業比重"
    assert "Product mix: system integration 17.31%" in mix.content
    assert (mix.published_at.date(), mix.fact_date, mix.fetched_at) == (date(2025, 5, 9), date(2024, 12, 31), NOW)
    assert len({section.key for section in report.sections}) == len(report.sections) == 3


async def test_a_year_the_site_lists_no_report_of_is_one_request_and_no_file(site: DocumentSite) -> None:
    assert await provider().fetch("5209", 2025) == AnnualReport(fiscal_year=2025, file=None)
    assert len(site.sent) == 1


async def test_a_report_of_scanned_images_is_named_with_no_section(site: DocumentSite, tmp_path: Path) -> None:
    site.pdf = write_pdf(tmp_path / "scanned.pdf", []).read_bytes()

    assert await provider().fetch("5209", 2024) == AnnualReport(fiscal_year=2024, file="2024_5209_20250528F04.pdf")


async def test_a_file_too_large_and_a_file_that_is_no_pdf_are_listed_and_not_readable_and_a_refused_connection_is_none(
    site: DocumentSite,
) -> None:
    unread = AnnualReport(fiscal_year=2024, file="2024_5209_20250528F04.pdf", readable=False)

    assert await provider(LATIN_REPORTS.model_copy(update={"max_bytes": 100})).fetch("5209", 2024) == unread

    site.pdf = b"<html>busy</html>"
    assert await provider().fetch("5209", 2024) == unread

    site.refuse_file = True
    assert await provider().fetch("5209", 2024) is None


async def test_a_worker_that_runs_out_of_time_is_killed_and_the_report_is_not_readable(
    site: DocumentSite, monkeypatch: pytest.MonkeyPatch
) -> None:
    stalled = "import time, sys\nif __name__ == '__main__':\n    time.sleep(60)\n"
    worker = Path(site.folder) / "stalled_worker.py"
    worker.write_text(stalled)
    monkeypatch.setattr(annual_report_text, "__file__", str(worker))
    started = time.monotonic()

    report = await provider(LATIN_REPORTS.model_copy(update={"read_timeout_seconds": 0.5})).fetch("5209", 2024)

    assert report == AnnualReport(fiscal_year=2024, file="2024_5209_20250528F04.pdf", readable=False)
    assert time.monotonic() - started < 10


async def test_the_worker_ends_itself_once_it_used_its_processor_time(tmp_path: Path) -> None:
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(Path(annual_report_text.__file__).parent)!r})\n"
        "import annual_report_text\n"
        "annual_report_text.bound_process(2**40, 1)\n"
        "while True:\n    pass\n"
    )
    spinning = await asyncio.create_subprocess_exec(sys.executable, "-I", "-c", script)

    assert await asyncio.wait_for(spinning.wait(), 30) < 0, "the system ended it by a signal, with nobody waiting on it"


async def test_a_report_leaves_no_file_behind(site: DocumentSite, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "temporary"))
    (tmp_path / "temporary").mkdir()

    assert await provider().fetch("5209", 2024) is not None
    assert list((tmp_path / "temporary").iterdir()) == []


async def test_only_a_personal_site_whose_settings_name_the_site_builds_the_adapter(database: DatabaseConnector) -> None:
    clock, logger = MovableClock(NOW), SilentLogger()
    public = CONFIG.model_copy(update={"audience": Audience.PUBLIC})
    older_file = REPORTS.model_copy(update={"index_url": ""})
    unset = CONFIG.model_copy(update={"sources": CONFIG.sources.model_copy(update={"annual_reports": older_file})})

    assert isinstance(create_annual_report_provider(CONFIG, database, clock, logger), TwseAnnualReportProvider)
    assert create_annual_report_provider(public, database, clock, logger) is None
    assert create_annual_report_provider(unset, database, clock, logger) is None


# ---------------------------------------------------- when due ---------------------------------------------------- #


@pytest.mark.parametrize(
    ("held_year", "checked_days_ago", "today", "looked_for"),
    [
        (None, None, date(2026, 11, 15), 2025),
        (None, None, date(2026, 5, 31), 2024),
        (2025, 30, date(2026, 11, 15), None),
        (2024, 30, date(2026, 5, 31), None),
        (2024, 300, date(2026, 6, 1), 2025),
        (2024, 3, date(2026, 6, 10), None),
        (2024, 7, date(2026, 6, 10), 2025),
        (None, 6, date(2026, 11, 15), None),
        (None, 7, date(2026, 11, 15), 2025),
    ],
)
async def test_the_newest_report_is_looked_for_yearly_from_june_then_weekly_until_it_appears(
    held_year: int | None, checked_days_ago: int | None, today: date, looked_for: int | None
) -> None:
    now = datetime(today.year, today.month, today.day, 10, tzinfo=TAIWAN_TIMEZONE)
    checked = None if checked_days_ago is None else now - timedelta(days=checked_days_ago)
    profile = CompanyProfile(stock_id="5209", annual_report_year=held_year, annual_report_checked_at=checked)

    assert AnnualReportDueRule(first_month=6, retry_days=7).apply(profile, now) == looked_for


def section(stock_id: str, fiscal_year: int, name: str = "product_mix") -> Article:
    return Article(
        stock_id=stock_id,
        source=InformationSource.ANNUAL_REPORT,
        content_type=ContentType.REPORT,
        title=f"{fiscal_year} {name}",
        content="系統整合收入 17.31%",
        url=f"https://doc.example/{stock_id}/{fiscal_year}#{name}",
        published_at=NOW - timedelta(days=150),
        fetched_at=NOW,
    )


class Refresh:
    def __init__(self) -> None:
        self.clock = MovableClock(NOW)
        self.reports = FakeAnnualReportProvider()
        self.profiles = FakeCompanyProfileRepository()
        self.store = FakeArticleStore(self.clock, timedelta(days=730), 300)
        self.step = AnnualReportRefresh(self.reports, self.profiles, self.store, self.clock, CONFIG, SilentLogger())


async def test_a_due_company_s_report_is_read_once_and_its_sections_are_kept() -> None:
    refresh = Refresh()
    refresh.reports.listed[("5209", 2025)] = AnnualReport(fiscal_year=2025, file="2025_5209.pdf", sections=[section("5209", 2025)])

    assert await refresh.step.execute(["5209", "5209"]) == (1, 0)
    assert await refresh.step.execute(["5209"]) == (0, 0)

    profile = refresh.profiles.rows["5209"]
    assert (profile.annual_report_year, profile.annual_report_file, profile.annual_report_checked_at) == (2025, "2025_5209.pdf", NOW)
    assert [article.title for article in await refresh.store.references("5209")] == ["2025 product_mix"]
    assert refresh.reports.asked == [("5209", 2025)]


async def test_a_company_with_nothing_held_gets_the_year_before_while_the_newest_is_not_listed() -> None:
    refresh = Refresh()
    refresh.reports.listed[("5209", 2024)] = AnnualReport(fiscal_year=2024, file="2024_5209.pdf", sections=[section("5209", 2024)])

    assert await refresh.step.execute(["5209"]) == (1, 0)
    assert refresh.reports.asked == [("5209", 2025), ("5209", 2024)]
    assert refresh.profiles.rows["5209"].annual_report_year == 2024

    refresh.clock.current = NOW + timedelta(days=6)
    assert await refresh.step.execute(["5209"]) == (0, 0)

    refresh.clock.current = NOW + timedelta(days=7)
    refresh.reports.listed[("5209", 2025)] = AnnualReport(fiscal_year=2025, file="2025_5209.pdf", sections=[section("5209", 2025)])
    assert await refresh.step.execute(["5209"]) == (1, 0)
    assert refresh.reports.asked[2:] == [("5209", 2025)]
    assert sorted(article.title for article in await refresh.store.references("5209")) == ["2024 product_mix", "2025 product_mix"]


async def test_a_company_with_no_report_listed_is_marked_and_looked_for_again_a_week_later() -> None:
    refresh = Refresh()

    assert await refresh.step.execute(["0050"]) == (0, 0)
    profile = refresh.profiles.rows["0050"]
    assert (profile.annual_report_year, profile.annual_report_file, profile.annual_report_checked_at) == (None, None, NOW)
    assert await refresh.store.references("0050") == []

    assert await refresh.step.execute(["0050"]) == (0, 0)
    assert len(refresh.reports.asked) == 2

    refresh.clock.current = NOW + timedelta(days=7)
    await refresh.step.execute(["0050"])
    assert len(refresh.reports.asked) == 4


async def test_a_report_with_no_text_is_named_with_no_section_and_not_fetched_again_this_year() -> None:
    refresh = Refresh()
    refresh.reports.listed[("5209", 2025)] = AnnualReport(fiscal_year=2025, file="2025_5209.pdf")

    assert await refresh.step.execute(["5209"]) == (1, 0)
    refresh.clock.current = NOW + timedelta(days=30)
    assert await refresh.step.execute(["5209"]) == (0, 0)

    assert await refresh.store.references("5209") == []
    assert refresh.reports.asked == [("5209", 2025)]


async def test_a_report_that_cannot_be_read_holds_up_no_other_company_and_is_looked_for_again_a_week_later() -> None:
    refresh = Refresh()
    refresh.reports.listed[("5209", 2025)] = AnnualReport(fiscal_year=2025, file="2025_5209.pdf", readable=False)
    refresh.reports.listed[("2330", 2025)] = AnnualReport(fiscal_year=2025, file="2025_2330.pdf", sections=[section("2330", 2025)])

    assert await refresh.step.execute(["5209", "2330"]) == (1, 0)
    assert await refresh.step.execute(["5209", "2330"]) == (0, 0)

    unread = refresh.profiles.rows["5209"]
    assert (unread.annual_report_year, unread.annual_report_file, unread.annual_report_checked_at) == (None, None, NOW)
    assert refresh.profiles.rows["2330"].annual_report_year == 2025
    assert refresh.reports.asked == [("5209", 2025), ("2330", 2025)]

    refresh.clock.current = NOW + timedelta(days=7)
    await refresh.step.execute(["5209"])

    assert refresh.reports.asked[-1] == ("5209", 2025)


async def test_a_run_stops_at_the_first_refusal_and_the_next_one_reads_only_the_rest() -> None:
    refresh = Refresh()
    refresh.reports.refused = {"3443"}

    for stock_id in ("2465", "3443", "5209"):
        refresh.reports.listed[(stock_id, 2025)] = AnnualReport(fiscal_year=2025, file=f"2025_{stock_id}.pdf")

    assert await refresh.step.execute(["2465", "3443", "5209"]) == (1, 2)

    refresh.reports.refused = set()
    assert await refresh.step.execute(["2465", "3443", "5209"]) == (2, 0)
    assert [stock_id for stock_id, _ in refresh.reports.asked] == ["2465", "3443", "3443", "5209"]


async def test_a_site_that_reads_no_annual_report_reads_nothing() -> None:
    refresh = Refresh()
    step = AnnualReportRefresh(None, refresh.profiles, refresh.store, refresh.clock, CONFIG, SilentLogger())

    assert await step.execute(["5209"]) == (0, 0)
    assert refresh.profiles.rows == {}


async def test_a_stock_s_news_never_pushes_its_annual_report_out_of_the_store(database: DatabaseConnector) -> None:
    clock = MovableClock(NOW)
    store = SqlArticleStore(database, clock, timedelta(days=730), 3)
    report = [section("5209", 2025, name) for name in ("business_scope", "product_mix")]
    news = [
        replace(
            section("5209", 2025),
            source=InformationSource.NEWS_MEDIA,
            url=f"https://news.example/{day}",
            published_at=NOW - timedelta(days=day),
        )
        for day in range(1, 6)
    ]

    await store.save(report)
    await store.save(news)

    assert [article.url for article in await store.latest("5209", 10)] == [f"https://news.example/{day}" for day in (1, 2, 3)], (
        "the news list holds the news alone"
    )
    assert sorted(article.url for article in await store.references("5209")) == sorted(article.url for article in report)
