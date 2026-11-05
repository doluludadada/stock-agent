from datetime import datetime

import pytest
from support.fakes import FakeMarketClock, FakeStockProvider, FakeWatchlistRepository
from trading_stack import SilentLogger, run_stats

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.types.enums import MarketType, WatchlistType
from b_application.use_cases.collect.intraday_candidates import IntradayCandidates
from b_application.use_cases.collect.stock_lookup import StockLookup
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)


def listed(*stock_ids: str) -> FakeStockProvider:
    provider = FakeStockProvider()
    provider.stocks = {stock_id: Stock(stock_id=stock_id, market=MarketType.TPEX) for stock_id in stock_ids}
    return provider


async def test_lookup_loads_each_requested_stock_once_and_reports_unknown_ids() -> None:
    stats = run_stats()

    stocks = await StockLookup(listed("2330", "2603"), SilentLogger()).execute([" 2330", "9999", "2330 ", "", "2603"], stats)

    assert [stock.stock_id for stock in stocks] == ["2330", "2603"]
    assert stocks[0].market == MarketType.TPEX
    assert stats.errors == ["Stock not found: 9999"]


async def test_intraday_candidates_are_held_stocks_plus_the_active_watchlist() -> None:
    clock = FakeMarketClock(NOW)
    watchlist = FakeWatchlistRepository(clock)
    await watchlist.save(
        [
            WatchlistEntry(stock_id=stock_id, watchlist_type=watchlist_type, created_at=NOW, expires_at=None)
            for stock_id, watchlist_type in [
                ("2330", WatchlistType.TECHNICAL),
                ("2330", WatchlistType.BUZZ),
                ("2603", WatchlistType.MANUAL),
                ("9999", WatchlistType.MANUAL),
            ]
        ]
    )
    stats = run_stats()
    held = Stock(stock_id="2330")

    candidates = await IntradayCandidates(listed("2330", "2603"), watchlist, SilentLogger()).execute(
        [held, Stock(stock_id="2317")], stats
    )

    assert [stock.stock_id for stock in candidates] == ["2330", "2317", "2603"]
    assert candidates[0] is held
    assert held.watchlist_types == {WatchlistType.TECHNICAL, WatchlistType.BUZZ}
    assert [stock.watchlist_types for stock in candidates[1:]] == [set(), {WatchlistType.MANUAL}]
    assert (stats.total_scanned, stats.errors) == (3, ["Stock not found: 9999"])
