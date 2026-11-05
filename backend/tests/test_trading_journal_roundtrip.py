"""What the SQL trading journal keeps of an account snapshot and of a specific-stock analysis's stocks."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from support.settings import shipped_config
from trading_stack import SilentLogger

from a_domain.model.analysis.ai_analysis_report import AiAnalysisReport
from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account, AccountSnapshot, Mark, Position
from a_domain.types.enums import InformationSource
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.user_dto import LEGACY_OWNER_ID
from c_infrastructure.database.repositories.trading_journal import TradingJournal
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

pytestmark = pytest.mark.asyncio

FILLED_AT = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)


@pytest_asyncio.fixture
async def journal(tmp_path: Path) -> AsyncIterator[TradingJournal]:
    db = DatabaseConnector(config=shipped_config(tmp_path), logger=SilentLogger())
    await db.init_db()
    yield TradingJournal(db.for_owner(LEGACY_OWNER_ID))
    await db.close()


async def test_a_snapshot_reads_back_each_position_at_its_mark_and_an_unpriced_one_at_its_cost(journal: TradingJournal) -> None:
    marked = Position(stock_id="2330", quantity=1000, average_cost=100.1425, mark=Mark(price=105.0, at=FILLED_AT))
    unpriced = Position(stock_id="2317", quantity=2000, average_cost=40.0)
    snapshot = AccountSnapshot(
        taken_at=FILLED_AT, run_id=uuid4(), order_id=uuid4(), account=Account(cash=500_000.0, positions=[marked, unpriced])
    )

    await journal.save_snapshot(snapshot)
    [read] = await journal.snapshots()

    assert (read.snapshot_id, read.taken_at, read.account.cash) == (snapshot.snapshot_id, FILLED_AT, 500_000.0)
    assert [(p.stock_id, p.quantity, p.average_cost, p.mark_price, p.marked_at) for p in read.account.positions] == [
        ("2330", 1000, 100.1425, 105.0, FILLED_AT),
        ("2317", 2000, 40.0, 40.0, None),
    ]
    assert read.account.positions[1].mark is None


async def test_a_specific_stock_report_keeps_the_price_and_the_reports_never_the_history_or_the_articles(
    journal: TradingJournal,
) -> None:
    daily = [Ohlcv(ts=FILLED_AT - timedelta(days=days), close=100.0 + days, volume=1000) for days in (3, 2, 1)]
    quote = Ohlcv(ts=FILLED_AT, open=104.0, high=106.0, low=103.0, close=105.5, volume=5000)
    article = Article(
        stock_id="2330", source=InformationSource.PTT_STOCK, title="t", content="c", published_at=FILLED_AT, fetched_at=FILLED_AT
    )
    technical = TechnicalReport(score=62, hard_failures=[], soft_failures=["Volume: below average"], observations=["Trend: detected"])
    ai = AiAnalysisReport(score=70, bullish_factors=["margin"], bearish_factors=[], summary="steady", raw_response="{}")
    stock = Stock(
        stock_id="2330",
        name="TSMC",
        ohlcv=daily,
        realtime_bar=quote,
        articles=[article],
        technical_report=technical,
        ai_report=ai,
        composite_score=66,
    )
    run_id = uuid4()

    await journal.save_stock_reports(run_id, [stock])
    stock.realtime_bar = None
    [read] = await journal.stock_reports_of(run_id)

    assert (read.stock_id, read.name, read.current_price, read.latest_market_data_at) == ("2330", "TSMC", 105.5, FILLED_AT)
    assert (read.technical_report, read.ai_report, read.composite_score) == (technical, ai, 66)
    assert (len(read.ohlcv), read.realtime_bar, read.articles) == (1, None, [])
