"""
What a personal site reads about a company beyond the exchanges' open data: its main business from MOPS's company
basic information, asked for when due, at the pace every request to MOPS shares, and never by a public site.
"""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from support.fakes import FakeCompanyBasicsProvider, FakeCompanyProfileRepository
from support.settings import shipped_config
from trading_stack import MovableClock, SilentLogger

from a_domain.model.market.company_profile import CompanyProfile
from a_domain.ports.market.company_basics_provider import CompanyBasics
from a_domain.types.enums import Audience, MarketType
from b_application.use_cases.collect.main_business_refresh import MainBusinessRefresh
from c_infrastructure import request_pace
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.market.mops_company_basics import MopsCompanyBasicsProvider
from c_infrastructure.request_pace import PacedHost, RequestPace, SharedRequestPace
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE
from d_presentation.dependencies import create_company_basics_provider

pytestmark = pytest.mark.asyncio

CONFIG = shipped_config()
MOPS = CONFIG.sources.mops
FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 15, 10, 0, tzinfo=TAIWAN_TIMEZONE)
ANSWERS = {"5209": "mops_api_t05st03_5209.json", "0050": "mops_api_t05st03_0050.json"}
"""MOPS's JSON answers as served on 2026-11-15: a company's basic information, and its refusal of an ETF's code."""


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """The requests MOPS got. It answers a company's fixture, 500 for 9999 and refuses the connection for 1111."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        stock_id = json.loads(request.content)["companyId"]

        if stock_id == "1111":
            raise httpx.ConnectError("Connection refused")

        if stock_id not in ANSWERS:
            return httpx.Response(500)

        return httpx.Response(200, content=(FIXTURES / ANSWERS[stock_id]).read_bytes())

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    return requests


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """How long each request waited for its turn: the pace sleeps here instead of on the clock."""
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(request_pace.asyncio, "sleep", sleep)
    return slept


def mops_provider(pace: RequestPace | None = None) -> MopsCompanyBasicsProvider:
    return MopsCompanyBasicsProvider(MOPS, pace or RequestPace(), SilentLogger())


async def test_a_company_s_main_business_and_english_name_come_from_one_request(sent: list[httpx.Request]) -> None:
    basics = await mops_provider().fetch("5209")

    assert basics == CompanyBasics(
        main_business=(
            "各項控制系統軟硬體之分項與整體之可行性研究、規劃、設計、採購、軟硬體組合.監造.安裝.校測.試車.維護及操作等。"
            "、電腦軟.硬體.儀器之進口代理及銷售。"
        ),
        english_name="CTCI Advanced Systems Inc.",
        url=MOPS.company_basics_page_url.format(stock_id="5209"),
    )
    assert [(request.method, str(request.url), json.loads(request.content)) for request in sent] == [
        ("POST", MOPS.company_basics_url, {"companyId": "5209"})
    ]


async def test_a_request_names_a_browser_and_mops_and_nothing_of_this_installation(sent: list[httpx.Request]) -> None:
    await mops_provider().fetch("5209")

    headers = sent[0].headers
    assert headers["user-agent"].startswith("Mozilla/5.0") and "stock" not in headers["user-agent"].lower()
    assert (headers["origin"], headers["referer"]) == (MOPS.company_basics_origin, f"{MOPS.company_basics_origin}/")
    assert "cookie" not in headers and "authorization" not in headers


@pytest.mark.usefixtures("sent")
async def test_a_code_mops_holds_no_company_of_is_answered_with_no_business() -> None:
    basics = await mops_provider().fetch("0050")

    assert basics is not None
    assert (basics.main_business, basics.english_name) == (None, None)


@pytest.mark.usefixtures("sent")
@pytest.mark.parametrize("stock_id", ["1111", "9999"])
async def test_a_refused_connection_and_a_failed_answer_are_none_and_never_raise(stock_id: str) -> None:
    assert await mops_provider().fetch(stock_id) is None


@pytest.mark.usefixtures("sent")
async def test_requests_to_mops_leave_one_interval_apart_whoever_shares_the_pace(waits: list[float]) -> None:
    pace = RequestPace()
    first, second = mops_provider(pace), mops_provider(pace)

    await first.fetch("5209")
    await asyncio.gather(second.fetch("5209"), first.fetch("0050"))

    assert len(waits) == 2
    assert all(MOPS.request_interval_seconds - 1 < wait <= MOPS.request_interval_seconds for wait in waits)
    assert MOPS.request_interval_seconds == 5


def refresh(
    basics: FakeCompanyBasicsProvider | None, profiles: FakeCompanyProfileRepository, clock: MovableClock
) -> MainBusinessRefresh:
    return MainBusinessRefresh(basics, profiles, clock, CONFIG, SilentLogger())


async def test_a_company_never_asked_for_is_read_and_kept_beside_what_the_exchange_gave() -> None:
    basics, profiles, clock = FakeCompanyBasicsProvider(), FakeCompanyProfileRepository(), MovableClock(NOW)
    listed = CompanyProfile(stock_id="5209", market=MarketType.TPEX, short_name="新鼎", chairman="鍾士偉", fetched_at=NOW)
    await profiles.save_listings([listed])
    basics.served["5209"] = CompanyBasics(main_business="控制系統整合", english_name="CTCI ASI", url="https://mops.example/5209")

    assert await refresh(basics, profiles, clock).execute(["5209", "5209", "8089"]) == (2, 0)

    assert profiles.rows["5209"] == replace(
        listed,
        main_business="控制系統整合",
        english_name="CTCI ASI",
        main_business_url="https://mops.example/5209",
        main_business_fetched_at=NOW,
    )
    assert profiles.rows["8089"].main_business is None and profiles.rows["8089"].main_business_fetched_at == NOW
    assert basics.asked == ["5209", "8089"]


async def test_a_company_is_asked_for_again_only_a_quarter_later() -> None:
    basics, profiles, clock = FakeCompanyBasicsProvider(), FakeCompanyProfileRepository(), MovableClock(NOW)
    step = refresh(basics, profiles, clock)
    await step.execute(["5209"])

    clock.current = NOW + timedelta(days=MOPS.company_basics_max_age_days - 1)
    assert await step.execute(["5209"]) == (0, 0)

    clock.current = NOW + timedelta(days=MOPS.company_basics_max_age_days)
    assert await step.execute(["5209"]) == (1, 0)
    assert basics.asked == ["5209", "5209"]


async def test_a_run_stops_at_the_first_refusal_and_the_next_one_reads_only_the_rest() -> None:
    basics, profiles, clock = FakeCompanyBasicsProvider(), FakeCompanyProfileRepository(), MovableClock(NOW)
    basics.refused = {"3443"}
    step = refresh(basics, profiles, clock)

    assert await step.execute(["2465", "3443", "5209", "8089"]) == (1, 3)
    assert basics.asked == ["2465", "3443"]

    basics.refused = set()
    assert await step.execute(["2465", "3443", "5209", "8089"]) == (3, 0)
    assert basics.asked == ["2465", "3443", "3443", "5209", "8089"]


async def test_a_site_that_reads_no_mops_reads_nothing() -> None:
    profiles = FakeCompanyProfileRepository()

    assert await refresh(None, profiles, MovableClock(NOW)).execute(["5209"]) == (0, 0)
    assert profiles.rows == {}


async def test_only_a_personal_site_whose_settings_name_the_addresses_builds_the_adapter(database: DatabaseConnector) -> None:
    logger = SilentLogger()
    public = CONFIG.model_copy(update={"audience": Audience.PUBLIC})
    older_file = CONFIG.sources.mops.model_copy(update={"company_basics_url": ""})
    unset = CONFIG.model_copy(update={"sources": CONFIG.sources.model_copy(update={"mops": older_file})})

    assert isinstance(create_company_basics_provider(CONFIG, database, logger), MopsCompanyBasicsProvider)
    assert create_company_basics_provider(public, database, logger) is None
    assert create_company_basics_provider(unset, database, logger) is None


async def test_two_processes_that_ask_one_host_leave_one_interval_apart_and_another_host_does_not_wait(
    database: DatabaseConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(request_pace.asyncio, "sleep", sleep)
    server, command = SharedRequestPace(database, PacedHost.MOPS), SharedRequestPace(database, PacedHost.MOPS)

    await asyncio.gather(server.wait(5), command.wait(5), server.wait(5))
    await SharedRequestPace(database, PacedHost.DOCUMENT_SITE).wait(5)

    assert sorted(round(wait) for wait in slept) == [0, 0, 5, 10]
