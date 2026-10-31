from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter
from a_domain.model.fundamentals.quarter_eps import QuarterEps
from a_domain.types.enums import MarketType
from b_application.config.market_data_config import MarketHoursConfig
from b_application.config.sources_config import SourcesConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.market.mops_fundamentals_provider import MopsFundamentalsProvider
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock

SOURCES = SourcesConfig.from_appsetting()

FIXTURES = Path(__file__).parent / "fixtures"
Q = FiscalQuarter
BEING_FILED = Q(2026, 3)
FINAL = Q(2025, 4)


class SilentLogger:
    def _drop(self, message: str) -> None:
        return None

    info = warning = debug = error = success = trace = critical = exception = _drop


class MovableClock(TaiwanMarketClock):
    def __init__(self) -> None:
        super().__init__(MarketHoursConfig())
        self.current = datetime(2026, 10, 30, 18, 0, tzinfo=TAIWAN_TIMEZONE)

    def now(self) -> datetime:
        return self.current


class FakeMops:
    """Stands in for the HTTP download: one answer per (market, quarter), None for a failed request."""

    def __init__(self) -> None:
        self.pages: dict[tuple[MarketType, FiscalQuarter], dict[str, float] | None] = {
            (MarketType.TWSE, BEING_FILED): {"1232": 8.03},
            (MarketType.TPEX, BEING_FILED): {},
            (MarketType.TWSE, FINAL): {"2330": 66.26, "1101": -1.60},
            (MarketType.TPEX, FINAL): {"6488": 20.10},
        }
        self.requests: list[tuple[MarketType, FiscalQuarter]] = []

    async def download(self, market: MarketType, quarter: FiscalQuarter) -> dict[str, float] | None:
        self.requests.append((market, quarter))
        return self.pages.get((market, quarter))


async def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[MopsFundamentalsProvider, FakeMops, MovableClock]:
    config = SimpleNamespace(project_root=tmp_path, db=SimpleNamespace(user=None, password=None, host=None, name=None, port=5432))
    db = DatabaseConnector(config=cast(Any, config), logger=SilentLogger())
    await db.init_db()
    clock = MovableClock()
    provider = MopsFundamentalsProvider(db=db, market_clock=clock, mops=SOURCES.mops, logger=SilentLogger())
    mops = FakeMops()
    monkeypatch.setattr(provider, "download", mops.download)
    return provider, mops, clock


def parser() -> MopsFundamentalsProvider:
    """Parsing reads no database and no clock."""
    return MopsFundamentalsProvider(db=cast(Any, None), market_clock=MovableClock(), mops=SOURCES.mops, logger=SilentLogger())


def test_parser_reads_every_industry_table_of_a_real_page() -> None:
    html = (FIXTURES / "mops_t163sb04_sii_115_02.html").read_text(encoding="utf-8")

    assert parser().parse_cumulative_eps(html) == {
        "2801": 0.94,
        "2855": 6.96,
        "1101": 0.38,
        "1213": -0.56,
        "2330": 49.33,
        "2880": 1.24,
        "2816": 7.84,
        "1409": 1.18,
    }


def test_parser_reads_an_unpublished_season_as_no_filings_yet() -> None:
    html = (FIXTURES / "mops_t163sb04_sii_115_04_unpublished.html").read_text(encoding="utf-8")

    assert parser().parse_cumulative_eps(html) == {}


def test_parser_rejects_a_page_it_does_not_recognise() -> None:
    assert parser().parse_cumulative_eps("<html><body>系統忙碌中，請稍後再試</body></html>") is None


@pytest.mark.asyncio
async def test_markets_are_merged_and_pages_are_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider, mops, _ = await build(tmp_path, monkeypatch)

    first = await provider.fetch_cumulative_eps([BEING_FILED, FINAL])
    second = await provider.fetch_cumulative_eps([BEING_FILED, FINAL])

    final = first[FINAL]
    assert isinstance(final, QuarterEps)
    assert final.cumulative_eps == {"2330": 66.26, "1101": -1.60, "6488": 20.10}
    assert final.fetched_at == datetime(2026, 10, 30, 18, 0, tzinfo=TAIWAN_TIMEZONE)
    assert len(mops.requests) == 4
    assert second == first


@pytest.mark.asyncio
async def test_quarter_being_filed_is_refetched_after_six_hours_and_final_quarter_never(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, mops, clock = await build(tmp_path, monkeypatch)
    await provider.fetch_cumulative_eps([BEING_FILED, FINAL])
    mops.requests.clear()
    mops.pages[(MarketType.TWSE, BEING_FILED)] = {"1232": 8.03, "2330": 70.0}

    clock.current += timedelta(hours=5)
    await provider.fetch_cumulative_eps([BEING_FILED, FINAL])
    assert mops.requests == []

    clock.current += timedelta(hours=2)
    filings = await provider.fetch_cumulative_eps([BEING_FILED, FINAL])

    assert set(mops.requests) == {(MarketType.TWSE, BEING_FILED), (MarketType.TPEX, BEING_FILED)}
    being_filed = filings[BEING_FILED]
    assert isinstance(being_filed, QuarterEps)
    assert being_filed.cumulative_eps == {"1232": 8.03, "2330": 70.0}


@pytest.mark.asyncio
async def test_failed_refresh_serves_the_cached_page_marked_as_a_failed_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, mops, clock = await build(tmp_path, monkeypatch)
    fresh = (await provider.fetch_cumulative_eps([BEING_FILED]))[BEING_FILED]
    mops.pages[(MarketType.TWSE, BEING_FILED)] = None

    clock.current += timedelta(hours=7)
    filings = await provider.fetch_cumulative_eps([BEING_FILED])

    being_filed = filings[BEING_FILED]
    assert isinstance(fresh, QuarterEps) and not fresh.refresh_failed
    assert isinstance(being_filed, QuarterEps)
    assert being_filed.cumulative_eps == {"1232": 8.03}
    assert being_filed.fetched_at == datetime(2026, 10, 30, 18, 0, tzinfo=TAIWAN_TIMEZONE)
    assert being_filed.refresh_failed


@pytest.mark.asyncio
async def test_failed_market_without_a_cached_page_fails_the_quarter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider, mops, _ = await build(tmp_path, monkeypatch)
    mops.pages[(MarketType.TPEX, FINAL)] = None

    filings = await provider.fetch_cumulative_eps([FINAL])

    assert filings == {FINAL: None}


@pytest.mark.asyncio
async def test_empty_page_for_a_final_quarter_is_a_failure_and_is_not_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider, mops, _ = await build(tmp_path, monkeypatch)
    mops.pages[(MarketType.TWSE, FINAL)] = {}

    assert await provider.fetch_cumulative_eps([FINAL]) == {FINAL: None}

    mops.pages[(MarketType.TWSE, FINAL)] = {"2330": 66.26}
    filings = await provider.fetch_cumulative_eps([FINAL])

    final = filings[FINAL]
    assert isinstance(final, QuarterEps)
    assert final.cumulative_eps == {"2330": 66.26, "6488": 20.10}


@pytest.mark.asyncio
async def test_industries_merge_every_market_and_refetch_a_market_only_once_its_list_is_a_day_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, _, clock = await build(tmp_path, monkeypatch)
    feeds: dict[MarketType, dict[str, str] | None] = {MarketType.TWSE: {"2330": "半導體業"}, MarketType.TPEX: None}
    requests: list[MarketType] = []

    async def fetch_market_industries(market: MarketType) -> dict[str, str] | None:
        requests.append(market)
        return feeds[market]

    monkeypatch.setattr(provider, "fetch_market_industries", fetch_market_industries)

    assert await provider.fetch_industries() == {"2330": "半導體業"}

    feeds[MarketType.TPEX] = {"6488": "半導體業"}
    clock.current += timedelta(hours=1)
    assert await provider.fetch_industries() == {"2330": "半導體業", "6488": "半導體業"}

    feeds[MarketType.TWSE] = None
    clock.current += timedelta(hours=24)
    assert await provider.fetch_industries() == {"2330": "半導體業", "6488": "半導體業"}
    assert requests == [MarketType.TWSE, MarketType.TPEX, MarketType.TPEX, MarketType.TWSE, MarketType.TPEX]
