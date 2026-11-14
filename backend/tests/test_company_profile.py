"""
Each listed company's profile: what the exchanges' OpenAPI serves of it, kept one per stock by the open-data archive's
step, on every audience.
"""

import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
from support.fakes import FakeCompanyProfileRepository, FakeDailyCloseArchive, FakeStockProvider
from support.settings import shipped_config
from trading_stack import SilentLogger

from a_domain.model.market.company_profile import CompanyProfile
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.types.enums import MarketType
from b_application.config.market_data_config import MarketDataConfig, MarketHoursConfig
from b_application.use_cases.collect.daily_close_archiver import DailyCloseArchiver
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.company_profile_repository import SqlCompanyProfileRepository
from c_infrastructure.market.exchange_text import web_address
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock

pytestmark = pytest.mark.asyncio

SOURCES = shipped_config().sources
FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 14, 20, 0, tzinfo=TAIWAN_TIMEZONE)
PROFILE_FILES = {
    SOURCES.exchange.company_profiles[MarketType.TWSE].url: "twse_t187ap03_l.json",
    SOURCES.exchange.company_profiles[MarketType.TPEX].url: "tpex_mopsfin_t187ap03_o.json",
}
"""Two real rows of each exchange's company basic data as served on 2026-11-14."""


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, str]]]:
    """What the two profile endpoints answer, which a test may change; an endpoint taken out answers 503."""
    answers = {url: json.loads((FIXTURES / name).read_text(encoding="utf-8")) for url, name in PROFILE_FILES.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        rows = answers.get(str(request.url))
        return httpx.Response(503) if rows is None else httpx.Response(200, json=rows)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(TaiwanMarketClock, "now", lambda clock: NOW)
    return answers


def exchange() -> TaiwanStockProvider:
    return TaiwanStockProvider(SOURCES.exchange, TaiwanMarketClock(MarketHoursConfig()), MarketDataConfig(), SilentLogger())


async def test_both_exchanges_rows_become_profiles_with_their_dates_capital_and_people(
    served: dict[str, list[dict[str, str]]],
) -> None:
    profiles = {profile.stock_id: profile for profile in await exchange().fetch_company_profiles()}

    assert sorted(profiles) == ["2465", "3443", "5209", "8089"]
    assert profiles["5209"] == CompanyProfile(
        stock_id="5209",
        market=MarketType.TPEX,
        full_name="新鼎系統股份有限公司",
        short_name="新鼎",
        english_short_name="CTCI ASI",
        industry_code="20",
        founded_on=date(1987, 8, 3),
        listed_on=date(2002, 2, 25),
        paid_in_capital=285_672_240,
        issued_shares=28_567_224,
        chairman="鍾士偉",
        general_manager="謝仁興",
        address="11Fl., 16, Fushan Rd., Beitou Dist.,Taipei City 112037, Taiwan, R.O.C.",
        website="http://www.asi.ctci.com",
        reported_on=date(2026, 11, 14),
        fetched_at=NOW,
    )
    twse = profiles["2465"]
    assert (twse.market, twse.full_name, twse.english_short_name) == (MarketType.TWSE, "麗臺科技股份有限公司", "LEADTEK")
    assert (twse.founded_on, twse.listed_on, twse.reported_on) == (date(1986, 10, 24), date(2001, 9, 19), date(2026, 11, 13))
    assert (twse.paid_in_capital, twse.issued_shares, twse.website) == (939_460_310, 93_946_031, "http://www.leadtek.com.tw")


async def test_a_blank_or_unreadable_field_is_none_and_a_row_without_a_company_is_left_out(
    served: dict[str, list[dict[str, str]]],
) -> None:
    url = SOURCES.exchange.company_profiles[MarketType.TWSE].url
    served[url] = [served[url][0] | {"成立日期": "", "實收資本額": "－", "董事長": " ", "網址": "無"}, {"出表日期": "1151113"}]

    profile, *others = [profile for profile in await exchange().fetch_company_profiles() if profile.market is MarketType.TWSE]

    assert others == []
    assert (profile.founded_on, profile.paid_in_capital, profile.chairman, profile.website) == (None, None, None, None)
    assert profile.listed_on == date(2001, 9, 19)


async def test_an_exchange_whose_profiles_fail_to_load_is_left_out(served: dict[str, list[dict[str, str]]]) -> None:
    del served[SOURCES.exchange.company_profiles[MarketType.TPEX].url]

    assert sorted(profile.stock_id for profile in await exchange().fetch_company_profiles()) == ["2465", "3443"]


@pytest.mark.parametrize(
    ("written", "address"),
    [
        ("www.asi.ctci.com", "http://www.asi.ctci.com"),
        (" https://www.guc-asic.com/ ", "https://www.guc-asic.com/"),
        ("HTTP://www.leadtek.com.tw", "HTTP://www.leadtek.com.tw"),
        ("", None),
        ("無", None),
        ("javascript:alert(1)", None),
        ("ftp://files.example.com", None),
        ("www.example.com 及 www.example.org", None),
        ("http://[bad", None),
    ],
)
async def test_a_website_is_an_http_address_or_nothing(written: str, address: str | None) -> None:
    assert web_address(written, "http") == address


async def test_the_archive_step_keeps_the_profiles_and_a_second_run_changes_nothing() -> None:
    stocks, profiles = FakeStockProvider(), FakeCompanyProfileRepository()
    stocks.stocks["5209"] = Stock(stock_id="5209", name="新鼎", market=MarketType.TPEX)
    stocks.closes["5209"] = Ohlcv(ts=NOW, open=100, high=101, low=99, close=100, volume=1000)
    stocks.company_profiles = [CompanyProfile(stock_id="5209", market=MarketType.TPEX, short_name="新鼎", fetched_at=NOW)]
    archiver = DailyCloseArchiver(stocks, FakeDailyCloseArchive(), profiles, SilentLogger())

    await archiver.execute()
    first = dict(profiles.rows)
    await archiver.execute()

    assert profiles.rows == first == {"5209": stocks.company_profiles[0]}


async def test_the_table_keeps_one_profile_per_stock_across_runs(database: DatabaseConnector) -> None:
    repository = SqlCompanyProfileRepository(database)
    listed = CompanyProfile(stock_id="5209", market=MarketType.TPEX, short_name="新鼎", paid_in_capital=285_672_240, fetched_at=NOW)

    await repository.save_listings([listed, listed])
    await repository.save_listings([listed])

    assert await repository.find("5209") == listed
    assert await repository.find("8089") is None


async def test_a_later_archive_run_keeps_what_other_sources_gave(database: DatabaseConnector) -> None:
    repository = SqlCompanyProfileRepository(database)
    listed = CompanyProfile(stock_id="5209", market=MarketType.TPEX, short_name="新鼎", chairman="鍾士偉", fetched_at=NOW)
    await repository.save_listings([listed])
    known = replace(
        listed,
        main_business="各項控制系統軟硬體",
        english_name="CTCI Advanced Systems Inc.",
        main_business_url="https://mops.example/5209",
        main_business_fetched_at=NOW,
        annual_report_year=2024,
        annual_report_file="2024_5209_20250528F04.pdf",
        annual_report_checked_at=NOW,
    )
    await repository.save(known)

    await repository.save_listings([replace(listed, chairman="新任董事長")])

    assert await repository.find("5209") == replace(known, chairman="新任董事長")
