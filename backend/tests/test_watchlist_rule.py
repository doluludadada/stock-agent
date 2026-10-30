from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from support.harness import build_harness, falling_history, rising_history

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.types.enums import WatchlistType
from b_application.schemas.config import AppConfig, WatchlistConfig
from b_application.use_cases.trade.watch_stocks import WatchStocks
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock

START = datetime(2026, 10, 30, 15, 0, tzinfo=TAIWAN_TIMEZONE)


class SilentLogger:
    def __getattr__(self, name: str):
        return lambda message: None


class SettableClock(TaiwanMarketClock):
    def __init__(self) -> None:
        super().__init__()
        self.current = START

    def now(self) -> datetime:
        return self.current


class Watchlist:
    """The real WatchStocks use case and SQLite repository, driven by a clock the test moves."""

    def __init__(self, db: DatabaseConnector) -> None:
        self.clock = SettableClock()
        self.repository = WatchlistRepository(db=db, logger=SilentLogger(), market_clock=self.clock)
        config = AppConfig(project_root=Path("."), watchlist=WatchlistConfig(automatic_expiry_hours=24))
        self.watch_stocks = WatchStocks(self.repository, self.clock, config, SilentLogger())

    async def add(self, watchlist_type: WatchlistType, *stock_ids: str):
        return await self.watch_stocks.execute([Stock(stock_id=stock_id) for stock_id in stock_ids], watchlist_type)

    async def active_types(self) -> dict[str, set[WatchlistType]]:
        watchlist = StockWatchlist.from_entries(await self.repository.get_active())
        return {stock.stock_id: stock.watchlist_types for stock in watchlist.willing_stocks}

    def advance(self, hours: int) -> None:
        self.clock.current = self.clock.current + timedelta(hours=hours)


@pytest_asyncio.fixture
async def watchlist(tmp_path: Path) -> AsyncIterator[Watchlist]:
    db = DatabaseConnector(config=AppConfig(project_root=tmp_path), logger=SilentLogger())
    await db.init_db()
    yield Watchlist(db)
    await db.close()


@pytest.mark.asyncio
async def test_adding_a_manual_stock_twice_reports_it_as_already_present(watchlist: Watchlist) -> None:
    first = await watchlist.add(WatchlistType.MANUAL, "2330")
    second = await watchlist.add(WatchlistType.MANUAL, "2330", "2317")

    assert first.added_stock_ids == ["2330"]
    assert first.already_present_stock_ids == []
    assert second.added_stock_ids == ["2317"]
    assert second.already_present_stock_ids == ["2330"]
    assert await watchlist.active_types() == {"2330": {WatchlistType.MANUAL}, "2317": {WatchlistType.MANUAL}}


@pytest.mark.asyncio
async def test_a_stock_holds_every_type_it_was_added_under_merged_by_stock_id(watchlist: Watchlist) -> None:
    await watchlist.add(WatchlistType.TECHNICAL, "2330", "2317")
    await watchlist.add(WatchlistType.BUZZ, "2330")
    manual = await watchlist.add(WatchlistType.MANUAL, "2330")

    assert manual.added_stock_ids == ["2330"]
    assert await watchlist.active_types() == {
        "2330": {WatchlistType.TECHNICAL, WatchlistType.BUZZ, WatchlistType.MANUAL},
        "2317": {WatchlistType.TECHNICAL},
    }


@pytest.mark.asyncio
async def test_automatic_entries_expire_after_the_configured_hours(watchlist: Watchlist) -> None:
    await watchlist.add(WatchlistType.TECHNICAL, "2330")
    await watchlist.add(WatchlistType.BUZZ, "2317")

    watchlist.advance(hours=23)
    assert set(await watchlist.active_types()) == {"2330", "2317"}

    watchlist.advance(hours=2)
    assert await watchlist.active_types() == {}


@pytest.mark.asyncio
async def test_manual_entries_never_expire_and_outlive_automatic_ones(watchlist: Watchlist) -> None:
    await watchlist.add(WatchlistType.TECHNICAL, "2330")
    await watchlist.add(WatchlistType.MANUAL, "2330")
    await watchlist.add(WatchlistType.TECHNICAL, "2330")

    watchlist.advance(hours=24 * 365)

    assert await watchlist.active_types() == {"2330": {WatchlistType.MANUAL}}


@pytest.mark.asyncio
async def test_selecting_an_automatic_stock_again_renews_its_expiry(watchlist: Watchlist) -> None:
    await watchlist.add(WatchlistType.TECHNICAL, "2330")
    watchlist.advance(hours=20)
    renewed = await watchlist.add(WatchlistType.TECHNICAL, "2330")

    watchlist.advance(hours=20)

    assert renewed.already_present_stock_ids == ["2330"]
    assert await watchlist.active_types() == {"2330": {WatchlistType.TECHNICAL}}


@pytest.mark.asyncio
async def test_an_expired_automatic_stock_is_added_again_not_reported_as_present(watchlist: Watchlist) -> None:
    await watchlist.add(WatchlistType.BUZZ, "2330")
    watchlist.advance(hours=30)

    again = await watchlist.add(WatchlistType.BUZZ, "2330")

    assert again.added_stock_ids == ["2330"]
    assert await watchlist.active_types() == {"2330": {WatchlistType.BUZZ}}


@pytest.mark.asyncio
async def test_the_cli_reports_newly_added_and_already_present_manual_stocks(capsys: pytest.CaptureFixture[str]) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", falling_history(100.0), realtime_price=100.0)

    await harness.run_menu("4", stock_ids="2330", add_to_watchlist=True)
    first_output = capsys.readouterr().out
    await harness.run_menu("4", stock_ids="2330 2317", add_to_watchlist=True)
    second_output = capsys.readouterr().out

    assert "Added to manual watchlist: 2330" in first_output
    assert "Added to manual watchlist: 2317" in second_output
    assert "Already present on manual watchlist: 2330" in second_output
    assert harness.watchlist.rows == [("2330", WatchlistType.MANUAL), ("2317", WatchlistType.MANUAL)]
