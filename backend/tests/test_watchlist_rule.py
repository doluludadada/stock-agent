from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
import pytest_asyncio
from pydantic import ValidationError
from support.harness import build_harness, falling_history, rising_history
from support.settings import shipped_config

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.types.enums import SettingsFile, WatchlistType
from b_application.config.market_data_config import MarketHoursConfig
from b_application.config.settings_loader import InvalidSettingsError
from b_application.config.trading_config import WatchlistConfig
from b_application.use_cases.trade.watch_stocks import WatchStocks
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.user_dto import LEGACY_OWNER_ID
from c_infrastructure.database.models.watchlist_dto import WatchlistDTO
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock
from d_presentation.dependencies import get_project_root, load_settings

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
        self.repository = WatchlistRepository(db.for_owner(LEGACY_OWNER_ID), SilentLogger(), self.clock)
        config = shipped_config().model_copy(
            update={"watchlist": WatchlistConfig(automatic_expiry_sessions=automatic_expiry_sessions)}
        )
        self.watch_stocks = WatchStocks(self.repository, self.clock, config, SilentLogger())

    async def add(self, watchlist_type: WatchlistType, *stock_ids: str):
        return await self.watch_stocks.execute([Stock(stock_id=stock_id) for stock_id in stock_ids], watchlist_type)

    async def active_types(self) -> dict[str, set[WatchlistType]]:
        types: dict[str, set[WatchlistType]] = {}

        for entry in await self.repository.get_active():
            types.setdefault(entry.stock_id, set()).add(entry.watchlist_type)

        return types

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
    db = DatabaseConnector(config=shipped_config(tmp_path), logger=SilentLogger())
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


def test_a_watchlist_entry_cannot_be_made_without_its_type() -> None:
    with pytest.raises(ValidationError, match="watchlist_type"):
        WatchlistEntry(stock_id="2330", created_at=FRIDAY_EVENING, expires_at=None)


@pytest.mark.asyncio
async def test_an_entry_without_a_type_is_refused_before_the_repository_can_save_it_as_technical(watchlist: Watchlist) -> None:
    with pytest.raises(ValidationError, match="watchlist_type"):
        WatchlistEntry(stock_id="2330", watchlist_type=cast(WatchlistType, None), created_at=FRIDAY_EVENING, expires_at=None)

    assert await watchlist.active_types() == {}


@pytest.mark.asyncio
async def test_a_stored_row_without_a_type_fails_to_load_instead_of_reading_as_technical(
    database: DatabaseConnector, watchlist: Watchlist
) -> None:
    async with database.for_owner(LEGACY_OWNER_ID).owner_session() as session:
        session.add(
            WatchlistDTO(
                owner_id=LEGACY_OWNER_ID, stock_id="2330", type=cast(WatchlistType, ""), created_at=FRIDAY_EVENING, expires_at=None
            )
        )
        await session.commit()

    with pytest.raises(ValueError, match="WatchlistType"):
        await watchlist.repository.get_active()


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
    root = get_project_root()
    text = (root / "config" / "appsetting.yaml").read_text(encoding="utf-8")
    old_key = text.replace("  automatic_expiry_sessions: 1", "  automatic_expiry_hours: 24", 1)

    assert load_settings(root).watchlist.automatic_expiry_sessions == 1
    with pytest.raises(InvalidSettingsError) as refused:
        load_settings(root, {SettingsFile.APPSETTING: old_key})

    assert [(problem.path, problem.message) for problem in refused.value.problems] == [
        ("watchlist.automatic_expiry_hours", "names no setting")
    ]
