from datetime import datetime, time, timedelta

import pytest
import pytest_asyncio
from trading_stack import MONDAY_10_00, MovableClock, SilentLogger, bar

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from b_application.schemas.config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.market.cached_price_provider import CachedPriceProvider

pytestmark = pytest.mark.asyncio


class CountingYahoo:
    """Serves the closed sessions plus, while a session runs, its in-progress bar at the latest price, as Yahoo does."""

    def __init__(self, clock: MovableClock) -> None:
        self.clock = clock
        self.calls = 0

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        self.calls += 1
        last_close = datetime.combine(self.clock.last_closed_session(), time(13, 30), tzinfo=self.clock.current.tzinfo)
        bars = [bar(last_close - timedelta(days=day), 100) for day in range(3, -1, -1)]

        if self.clock.is_market_open():
            bars.append(bar(self.clock.current.replace(hour=0), 110))

        return {stock.stock_id: [one.model_copy() for one in bars] for stock in stocks}

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        return {}


@pytest_asyncio.fixture
async def db(tmp_path):
    connector = DatabaseConnector(config=AppConfig(project_root=tmp_path), logger=SilentLogger())
    await connector.init_db()
    yield connector
    await connector.close()


async def test_history_holds_closed_sessions_and_is_refetched_when_a_newer_one_closes(db: DatabaseConnector) -> None:
    clock = MovableClock(MONDAY_10_00 + timedelta(days=1))
    yahoo = CountingYahoo(clock)
    cache = CachedPriceProvider(price_provider=yahoo, db=db, logger=SilentLogger(), market_clock=clock)
    seen = []

    for moment in ["Tue 10:00", "Tue 11:00", "Tue 14:00", "Sat 10:00", "Sat 12:00"]:
        day, hour = moment.split()
        clock.current = (MONDAY_10_00 + timedelta(days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].index(day))).replace(
            hour=int(hour[:2])
        )
        start, end = clock.history_window(30)
        bars = (await cache.fetch_history([Stock(stock_id="2330")], start, end))["2330"]
        seen.append((moment, yahoo.calls, clock.to_trading_date(bars[-1].ts).isoformat(), bars[-1].close))

    assert seen == [
        ("Tue 10:00", 1, "2026-10-19", 100),
        ("Tue 11:00", 1, "2026-10-19", 100),
        ("Tue 14:00", 2, "2026-10-20", 100),
        ("Sat 10:00", 3, "2026-10-23", 100),
        ("Sat 12:00", 3, "2026-10-23", 100),
    ]
