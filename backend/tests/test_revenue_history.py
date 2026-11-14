"""
The monthly revenue of past months on a personal site: which months a backfill reads (RevenueMonthsRule), MOPS's
summary CSV of one market and month read as the OpenAPI's summary is (trimmed real files in tests/fixtures), the
backfill that saves each month into the open-data archive and resumes where a failure stopped it, and the SQL archive's
reads of what it holds.
"""

import asyncio
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import text
from support.databases import BACKENDS, empty_database
from support.fakes import FakeDailyCloseArchive, FakeMarketClock, RecordingLogger
from support.settings import shipped_config
from test_daily_close_archive import refusing
from trading_stack import SilentLogger

from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.ports.market.daily_close_archive import OpenDataDownload
from a_domain.rules.fundamentals.filing import RevenueMonthsRule
from a_domain.types.enums import DatabaseBackend, MarketType
from a_domain.types.errors import ArchiveSaveRefused
from b_application.config.market_data_config import MarketDataConfig, MarketHoursConfig
from b_application.use_cases.collect.revenue_history_backfill import RevenueHistoryBackfill
from c_infrastructure.database.repositories.daily_close_archive import SqlDailyCloseArchive
from c_infrastructure.market.mops_fundamentals_provider import MopsFundamentalsProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock

CONFIG = shipped_config()
FIXTURES = Path(__file__).parent / "fixtures"
TWSE, TPEX = MarketType.TWSE, MarketType.TPEX
NOW = datetime(2025, 2, 12, 18, 0, tzinfo=TAIWAN_TIMEZONE)


def revenue(stock_id: str, market: MarketType, year: int, month: int, served: date, amount: float = 100.0) -> MonthlyRevenue:
    return MonthlyRevenue(
        stock_id=stock_id,
        year=year,
        month=month,
        market=market,
        served_date=served,
        company_name=stock_id,
        industry="",
        revenue=amount,
        previous_month_revenue=None,
        last_year_revenue=None,
        month_over_month_percent=None,
        year_over_year_percent=None,
        cumulative_revenue=None,
        last_year_cumulative_revenue=None,
        cumulative_year_over_year_percent=None,
        note="-",
    )


def test_a_backfill_reads_every_markets_months_from_firsts_to_last_months_oldest_first() -> None:
    due = RevenueMonthsRule(deadline_day=10).apply(date(2024, 11, 20), date(2025, 2, 12), {})

    assert due == [(TWSE, 2024, 11), (TPEX, 2024, 11), (TWSE, 2024, 12), (TPEX, 2024, 12), (TWSE, 2025, 1), (TPEX, 2025, 1)]


def test_a_month_served_after_the_deadline_of_the_month_after_it_is_held_and_one_served_before_it_is_read_again() -> None:
    served = {(TWSE, 2024, 12): date(2025, 1, 11), (TPEX, 2024, 12): date(2025, 1, 10), (TWSE, 2025, 1): date(2025, 2, 5)}

    due = RevenueMonthsRule(deadline_day=10).apply(date(2024, 12, 1), date(2025, 2, 12), served)

    assert due == [(TPEX, 2024, 12), (TWSE, 2025, 1), (TPEX, 2025, 1)]


def test_december_is_filed_by_the_deadline_in_january_of_the_next_year() -> None:
    rule = RevenueMonthsRule(deadline_day=10)

    assert rule.apply(date(2024, 12, 1), date(2025, 1, 31), {(TWSE, 2024, 12): date(2025, 1, 11)}) == [(TPEX, 2024, 12)]


def listing() -> TaiwanStockProvider:
    clock = TaiwanMarketClock(MarketHoursConfig())
    return TaiwanStockProvider(
        exchange=CONFIG.sources.exchange, market_clock=clock, market_data=MarketDataConfig(), logger=SilentLogger()
    )


@pytest.fixture
def served_files(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """MOPS over the fixture files: the address of each one, 404 for any other; the addresses asked, in order."""
    asked: list[str] = []
    files = {
        "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_113_6.csv": "mops_t21sc03_sii_113_6.csv",
        "https://mopsov.twse.com.tw/nas/t21/otc/t21sc03_113_6.csv": "mops_t21sc03_otc_113_6.csv",
    }
    real_client = httpx.AsyncClient

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        name = files.get(str(request.url))
        return httpx.Response(200, content=(FIXTURES / name).read_bytes()) if name else httpx.Response(404, text="<html>404</html>")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(answer)))
    return asked


def mops() -> MopsFundamentalsProvider:
    unspaced = CONFIG.sources.mops.model_copy(update={"request_interval_seconds": 0.0})
    return MopsFundamentalsProvider(
        db=cast(Any, None),
        market_clock=TaiwanMarketClock(MarketHoursConfig()),
        mops=unspaced,
        listing=listing(),
        logger=SilentLogger(),
        write_lock=asyncio.Lock(),
    )


@pytest.mark.asyncio
async def test_mops_summary_of_a_past_month_is_read_as_the_openapis_summary_with_its_slashed_roc_dates(
    served_files: list[str],
) -> None:
    twse = await mops().fetch_monthly_revenues(TWSE, 2024, 6)
    tpex = await mops().fetch_monthly_revenues(TPEX, 2024, 6)

    assert served_files == [
        "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_113_6.csv",
        "https://mopsov.twse.com.tw/nas/t21/otc/t21sc03_113_6.csv",
    ]
    assert twse is not None and tpex is not None
    assert [(item.stock_id, item.market, item.year, item.month, item.served_date) for item in twse + tpex] == [
        ("1101", TWSE, 2024, 6, date(2026, 11, 9)),
        ("1102", TWSE, 2024, 6, date(2026, 11, 9)),
        ("2330", TWSE, 2024, 6, date(2026, 11, 9)),
        ("6488", TPEX, 2024, 6, date(2026, 11, 10)),
    ]
    tsmc = twse[2]
    assert (tsmc.revenue, tsmc.previous_month_revenue, tsmc.last_year_revenue) == (207868693.0, 229620372.0, 156404174.0)
    assert (tsmc.company_name, tsmc.industry, tsmc.note) == ("台積電", "半導體業", "-")


@pytest.mark.asyncio
async def test_a_month_mops_does_not_serve_is_none(served_files: list[str]) -> None:
    assert await mops().fetch_monthly_revenues(TWSE, 2024, 7) is None
    assert served_files == ["https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_113_7.csv"]


class ServedMonths:
    """MOPS's summaries per (market, year, month); a month it does not hold fails, as a request that fails does."""

    def __init__(self, months: dict[tuple[MarketType, int, int], list[MonthlyRevenue]]) -> None:
        self.months = months
        self.asked: list[tuple[MarketType, int, int]] = []

    async def fetch_monthly_revenues(self, market: MarketType, year: int, month: int) -> list[MonthlyRevenue] | None:
        self.asked.append((market, year, month))
        return self.months.get((market, year, month))


def backfill(served: ServedMonths | None, archive: FakeDailyCloseArchive, logger: RecordingLogger) -> RevenueHistoryBackfill:
    return RevenueHistoryBackfill(cast(Any, served), cast(Any, archive), FakeMarketClock(NOW), CONFIG, logger)


@pytest.mark.asyncio
async def test_the_backfill_saves_each_month_it_reads_and_a_rerun_reads_only_what_a_failure_left() -> None:
    filed = date(2025, 2, 12)
    months = {
        (TWSE, 2024, 12): [revenue("2330", TWSE, 2024, 12, filed)],
        (TPEX, 2024, 12): [revenue("6488", TPEX, 2024, 12, filed)],
        (TPEX, 2025, 1): [revenue("6488", TPEX, 2025, 1, filed)],
    }
    served, archive, logger = ServedMonths(months), FakeDailyCloseArchive(), RecordingLogger()

    first = await backfill(served, archive, logger).execute(date(2024, 12, 1))

    assert first == (2, 4)
    assert served.asked == [(TWSE, 2024, 12), (TPEX, 2024, 12), (TWSE, 2025, 1)]
    assert sorted(archive.monthly_revenues) == [("2330", 2024, 12), ("6488", 2024, 12)]
    assert ("warning", "Revenue backfill stopped at 2025-01 twse: 2/4 months read") in logger.records

    months[(TWSE, 2025, 1)] = [revenue("2330", TWSE, 2025, 1, filed)]
    served.asked.clear()

    assert await backfill(served, archive, logger).execute(date(2024, 12, 1)) == (2, 2)
    assert served.asked == [(TWSE, 2025, 1), (TPEX, 2025, 1)]
    assert sorted(archive.monthly_revenues) == [("2330", 2024, 12), ("2330", 2025, 1), ("6488", 2024, 12), ("6488", 2025, 1)]


@pytest.mark.asyncio
async def test_a_month_the_archive_holds_from_the_openapi_before_its_deadline_is_read_again_from_mops() -> None:
    archive = FakeDailyCloseArchive()
    await archive.save(
        OpenDataDownload(
            stocks=[],
            indexes={},
            material_information=[],
            quarter_eps={},
            valuation_ratios=[],
            financial_reports=[],
            monthly_revenues=[revenue("2330", TWSE, 2025, 1, date(2025, 2, 6)), revenue("6488", TPEX, 2025, 1, date(2025, 2, 11))],
            exchange_news=[],
        )
    )
    served = ServedMonths({(TWSE, 2025, 1): [revenue("2330", TWSE, 2025, 1, date(2025, 2, 12), amount=120.0)]})

    assert await backfill(served, archive, RecordingLogger()).execute(date(2025, 1, 1)) == (1, 1)
    assert served.asked == [(TWSE, 2025, 1)]
    assert archive.monthly_revenues[("2330", 2025, 1)].revenue == 120.0


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_a_month_the_archive_could_not_save_fails_the_backfill_and_is_read_again_once_it_can(
    backend: DatabaseBackend, tmp_path: Path
) -> None:
    db = await empty_database(backend, tmp_path)
    await db.init_db()
    archive = SqlDailyCloseArchive(db, TaiwanMarketClock(MarketHoursConfig()), CONFIG.sources.exchange, 30, SilentLogger())
    filed = {
        (TWSE, 2025, 1): [revenue("2330", TWSE, 2025, 1, date(2025, 2, 12))],
        (TPEX, 2025, 1): [revenue("6488", TPEX, 2025, 1, date(2025, 2, 12))],
    }
    served = ServedMonths(filed)
    monthly = RevenueHistoryBackfill(cast(Any, served), archive, FakeMarketClock(NOW), CONFIG, SilentLogger())

    try:
        async with db.get_session() as session:
            for statement in refusing("monthly_revenue_archive", backend):
                await session.execute(text(statement))

            await session.commit()

        with pytest.raises(ArchiveSaveRefused, match="monthly_revenue_archive"):
            await monthly.execute(date(2025, 1, 1))

        async with db.get_session() as session:
            await session.execute(
                text(f"DROP TRIGGER refuse_rows{'' if backend == DatabaseBackend.SQLITE else ' ON monthly_revenue_archive'}")
            )
            await session.commit()

        served.asked.clear()

        assert await monthly.execute(date(2025, 1, 1)) == (2, 2)
        assert served.asked == [(TWSE, 2025, 1), (TPEX, 2025, 1)]
        assert sorted(await archive.revenue_history(date(2025, 1, 1), date(2025, 1, 31))) == [("2330", 2025, 1), ("6488", 2025, 1)]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_a_site_that_reads_no_mops_backfills_nothing() -> None:
    assert await backfill(None, FakeDailyCloseArchive(), RecordingLogger()).execute(date(2024, 1, 1)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_the_sql_archive_serves_the_latest_served_day_of_each_markets_month_and_the_revenue_of_a_span_of_months(
    backend: DatabaseBackend, tmp_path: Path
) -> None:
    db = await empty_database(backend, tmp_path)
    await db.init_db()
    archive = SqlDailyCloseArchive(db, TaiwanMarketClock(MarketHoursConfig()), CONFIG.sources.exchange, 30, SilentLogger())
    held = [
        revenue("2330", TWSE, 2024, 12, date(2025, 1, 9)),
        revenue("2317", TWSE, 2024, 12, date(2025, 1, 12)),
        revenue("6488", TPEX, 2024, 12, date(2026, 11, 10)),
        revenue("2330", TWSE, 2025, 1, date(2025, 2, 12)),
        revenue("2330", TWSE, 2025, 2, date(2025, 3, 12)),
    ]

    try:
        await archive.save(
            OpenDataDownload(
                stocks=[],
                indexes={},
                material_information=[],
                quarter_eps={},
                valuation_ratios=[],
                financial_reports=[],
                monthly_revenues=held,
                exchange_news=[],
            )
        )

        assert await archive.revenue_served() == {
            (TWSE, 2024, 12): date(2025, 1, 12),
            (TPEX, 2024, 12): date(2026, 11, 10),
            (TWSE, 2025, 1): date(2025, 2, 12),
            (TWSE, 2025, 2): date(2025, 3, 12),
        }
        span = await archive.revenue_history(date(2024, 12, 31), date(2025, 1, 1))
        assert span == {("2317", 2024, 12): 100.0, ("2330", 2024, 12): 100.0, ("6488", 2024, 12): 100.0, ("2330", 2025, 1): 100.0}
    finally:
        await db.close()
