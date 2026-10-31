from datetime import datetime

import pytest
from support.fakes import FakeMarketClock, FakeStockProvider, FakeWatchlistRepository
from trading_stack import SilentLogger, run_status

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist_entry import WatchlistEntry
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
    status = run_status()

    stocks = await StockLookup(listed("2330", "2603"), SilentLogger()).execute([" 2330", "9999", "2330 ", "", "2603"], status)

    assert [stock.stock_id for stock in stocks] == ["2330", "2603"]
    assert stocks[0].market == MarketType.TPEX
    assert status.stats.errors == ["Stock not found: 9999"]
    assert status.stocks_cache == {"2330": stocks[0], "2603": stocks[1]}


async def test_lookup_reuses_the_stock_this_run_already_loaded() -> None:
    status = run_status()
    held = Stock(stock_id="2330", name="held")
    status.stocks_cache["2330"] = held

    stocks = await StockLookup(listed("2330"), SilentLogger()).execute(["2330"], status)

    assert stocks == [held]
    assert stocks[0] is held


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
    status = run_status()
    held = Stock(stock_id="2330")
    status.held_stocks = [held, Stock(stock_id="2317")]
    status.stocks_cache["2330"] = held

    candidates = await IntradayCandidates(listed("2330", "2603"), watchlist, SilentLogger()).execute(status)

    assert [stock.stock_id for stock in candidates] == ["2330", "2317", "2603"]
    assert candidates[0] is held
    assert held.watchlist_types == {WatchlistType.TECHNICAL, WatchlistType.BUZZ}
    assert [stock.stock_id for stock in status.watchlist.willing_stocks] == ["2330", "2603"]
    assert status.stats.errors == ["Stock not found: 9999"]
