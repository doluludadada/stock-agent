from datetime import datetime, timedelta

import pytest
from trading_stack import SilentLogger, run_status

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.technical.calculation import IndicatorParameters
from b_application.schemas.config import AppConfig
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)


class ClockAt(TaiwanMarketClock):
    def now(self) -> datetime:
        return NOW


class QuoteFeed:
    def __init__(self, daily_close_at: datetime, quote_at: datetime) -> None:
        self._daily_close_at = daily_close_at
        self._quote_at = quote_at

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        bar = Ohlcv(ts=self._daily_close_at, open=100, high=100, low=100, close=100, volume=1000)
        return {stock.stock_id: [bar] for stock in stocks}

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        bar = Ohlcv(ts=self._quote_at, open=101, high=101, low=101, close=101, volume=10)
        return {stock.stock_id: bar for stock in stocks}


def collector(feed: QuoteFeed, tmp_path) -> MarketDataCollector:
    config = AppConfig(project_root=tmp_path)
    config.freshness.realtime_max_lag_minutes = 15
    config.freshness.history_max_lag_days = 10
    return MarketDataCollector(ohlcv_provider=feed, market_clock=ClockAt(), config=config, logger=SilentLogger())


@pytest.mark.parametrize(("days_old", "blocked"), [(10, 0), (11, 1)])
async def test_daily_history_older_than_the_history_limit_is_not_analysed(tmp_path, days_old: int, blocked: int) -> None:
    status = run_status()
    feed = QuoteFeed(daily_close_at=NOW - timedelta(days=days_old), quote_at=NOW)

    stock = Stock(stock_id="2330")

    await collector(feed, tmp_path).execute([stock], status, IndicatorParameters())

    assert status.stats.stale_market_data_count == blocked
    assert bool(stock.ohlcv) is not bool(blocked)


@pytest.mark.parametrize(("minutes_old", "stale"), [(15, False), (16, True)])
async def test_realtime_quotes_use_the_minute_limit_not_the_day_limit(tmp_path, minutes_old: int, stale: bool) -> None:
    status = run_status()
    feed = QuoteFeed(daily_close_at=NOW, quote_at=NOW - timedelta(minutes=minutes_old))

    await collector(feed, tmp_path).refresh_realtime([Stock(stock_id="2330")], status)

    assert ("2330" in status.stale_stock_ids) is stale
