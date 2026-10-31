from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import ValidationError
from support.harness import build_harness, falling_history, rising_history

from a_domain.model.market.stock import Stock
from a_domain.model.trading.stock_watchlist import StockWatchlist
from a_domain.types.enums import WatchlistType
from b_application.config.app_config import AppConfig
from b_application.config.market_data_config import MarketHoursConfig
from b_application.config.trading_config import WatchlistConfig
from b_application.use_cases.trade.watch_stocks import WatchStocks
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.system.config_loader import load_settings
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock

FRIDAY_EVENING = datetime(2026, 10, 30, 18, 0, tzinfo=TAIWAN_TIMEZONE)


class SilentLogger:
    def __getattr__(self, name: str):
        return lambda message: None


class SettableClock(TaiwanMarketClock):
    def __init__(self) -> None:
        super().__init__(MarketHoursConfig())
        self.current = FRIDAY_EVENING

    def now(self) -> datetime:
        return self.current


class Watchlist:
    """The real WatchStocks use case and SQLite repository, driven by a clock the test moves."""

    def __init__(self, db: DatabaseConnector, automatic_expiry_sessions: int = 1) -> None:
        self.clock = SettableClock()
        self.repository = WatchlistRepository(db=db, logger=SilentLogger(), market_clock=self.clock)
        config = AppConfig(project_root=Path("."), watchlist=WatchlistConfig(automatic_expiry_sessions=automatic_expiry_sessions))
        self.watch_stocks = WatchStocks(self.repository, self.clock, config, SilentLogger())

    async def add(self, watchlist_type: WatchlistType, *stock_ids: str):
        return await self.watch_stocks.execute([Stock(stock_id=stock_id) for stock_id in stock_ids], watchlist_type)

    async def active_types(self) -> dict[str, set[WatchlistType]]:
        watchlist = StockWatchlist.from_entries(await self.repository.get_active())
        return {stock.stock_id: stock.watchlist_types for stock in watchlist.willing_stocks}

    def advance(self, hours: int) -> None:
        self.clock.current = self.clock.current + timedelta(hours=hours)

    def move_to(self, moment: str) -> None:
        """A weekday and time after FRIDAY_EVENING, such as "Mon 13:29" or "next Mon 10:00"."""
        *week, day, clock = moment.split()
        days_ahead = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"].index(day) + 1 + (7 if week else 0)
        hour, minute = map(int, clock.split(":"))
        self.clock.current = (FRIDAY_EVENING + timedelta(days=days_ahead)).replace(hour=hour, minute=minute)


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[DatabaseConnector]:
    db = DatabaseConnector(config=AppConfig(project_root=tmp_path), logger=SilentLogger())
    await db.init_db()
    yield db
    await db.close()


@pytest.fixture
def watchlist(database: DatabaseConnector) -> Watchlist:
    return Watchlist(database)


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
async def test_friday_evenings_automatic_entries_are_active_for_mondays_session_and_expire_at_its_close(watchlist: Watchlist) -> None:
    await watchlist.add(WatchlistType.TECHNICAL, "2330")
    await watchlist.add(WatchlistType.BUZZ, "2317")

    watchlist.move_to("Mon 10:00")
    assert set(await watchlist.active_types()) == {"2330", "2317"}

    watchlist.move_to("Mon 13:29")
    assert set(await watchlist.active_types()) == {"2330", "2317"}

    watchlist.move_to("Mon 13:30")
    assert await watchlist.active_types() == {}


@pytest.mark.asyncio
async def test_automatic_entries_last_through_the_configured_number_of_sessions(database: DatabaseConnector) -> None:
    watchlist = Watchlist(database, automatic_expiry_sessions=3)
    await watchlist.add(WatchlistType.TECHNICAL, "2330")

    watchlist.move_to("Wed 13:29")
    assert set(await watchlist.active_types()) == {"2330"}

    watchlist.move_to("Wed 13:30")
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
    watchlist.move_to("Mon 10:00")
    renewed = await watchlist.add(WatchlistType.TECHNICAL, "2330")

    watchlist.move_to("Tue 13:29")

    assert renewed.already_present_stock_ids == ["2330"]
    assert await watchlist.active_types() == {"2330": {WatchlistType.TECHNICAL}}


@pytest.mark.asyncio
async def test_an_expired_automatic_stock_is_added_again_not_reported_as_present(watchlist: Watchlist) -> None:
    await watchlist.add(WatchlistType.BUZZ, "2330")
    watchlist.move_to("Mon 13:30")

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


def test_the_watchlist_config_counts_sessions_and_refuses_the_old_hours_key() -> None:
    assert load_settings().watchlist.automatic_expiry_sessions == 1

    with pytest.raises(ValidationError, match="automatic_expiry_hours"):
        WatchlistConfig.model_validate({"automatic_expiry_hours": 24})
