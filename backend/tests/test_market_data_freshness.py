from datetime import date, datetime, time, timedelta

import pytest
from trading_stack import SilentLogger, run_status

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from b_application.config.app_config import AppConfig
from b_application.config.market_data_config import MarketHoursConfig
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.collect.realtime_quote_feed import RealtimeQuoteFeed
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)
MISSING_FRIDAY = (
    "Daily history lacks the 2026-10-16 session for 2/2 stocks (2317, 2330): the price source has not published it, "
    "so their analysis ends at an earlier close. An exchange holiday also reads as missing."
)


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


def freshness_config(tmp_path) -> AppConfig:
    config = AppConfig(project_root=tmp_path)
    config.freshness.realtime_max_lag_minutes = 15
    config.freshness.history_max_lag_days = 10
    return config


def collector(feed: QuoteFeed, tmp_path) -> MarketDataCollector:
    return MarketDataCollector(
        ohlcv_provider=feed, market_clock=ClockAt(MarketHoursConfig()), config=freshness_config(tmp_path), logger=SilentLogger()
    )


def quote_feed(feed: QuoteFeed, tmp_path) -> RealtimeQuoteFeed:
    return RealtimeQuoteFeed(
        quote_provider=feed, market_clock=ClockAt(MarketHoursConfig()), config=freshness_config(tmp_path), logger=SilentLogger()
    )


@pytest.mark.parametrize(("days_old", "blocked"), [(10, 0), (11, 1)])
async def test_daily_history_older_than_the_history_limit_is_not_analysed(tmp_path, days_old: int, blocked: int) -> None:
    status = run_status()
    feed = QuoteFeed(daily_close_at=NOW - timedelta(days=days_old), quote_at=NOW)

    stock = Stock(stock_id="2330")

    await collector(feed, tmp_path).execute([stock], status)

    assert status.stats.stale_market_data_count == blocked
    assert bool(stock.ohlcv) is not bool(blocked)


@pytest.mark.parametrize(("minutes_old", "stale"), [(15, False), (16, True)])
async def test_realtime_quotes_use_the_minute_limit_not_the_day_limit(tmp_path, minutes_old: int, stale: bool) -> None:
    status = run_status()
    feed = QuoteFeed(daily_close_at=NOW, quote_at=NOW - timedelta(minutes=minutes_old))

    await quote_feed(feed, tmp_path).execute([Stock(stock_id="2330")], status)

    assert ("2330" in status.stale_stock_ids) is stale


@pytest.mark.parametrize(("last_session", "errors"), [(date(2026, 10, 16), []), (date(2026, 10, 15), [MISSING_FRIDAY])])
async def test_history_without_the_last_settled_session_is_a_run_error(tmp_path, last_session: date, errors: list[str]) -> None:
    status = run_status()
    feed = QuoteFeed(daily_close_at=datetime.combine(last_session, time(13, 30), TAIWAN_TIMEZONE), quote_at=NOW)
    stocks = [Stock(stock_id="2330"), Stock(stock_id="2317")]

    await collector(feed, tmp_path).execute(stocks, status)

    assert status.stats.errors == errors
    assert all(stock.ohlcv for stock in stocks)


class FailingQuoteFeed:
    def __init__(self) -> None:
        self.requests: list[list[str]] = []

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        self.requests.append([stock.stock_id for stock in stocks])
        raise ConnectionError("MIS unreachable")


async def test_a_failed_quote_fetch_blocks_every_asked_stock_once(tmp_path) -> None:
    status = run_status()
    feed = FailingQuoteFeed()
    stocks = [Stock(stock_id="2330"), Stock(stock_id="2317"), Stock(stock_id="2330")]

    await quote_feed(feed, tmp_path).execute(stocks, status)
    await quote_feed(feed, tmp_path).execute(stocks, status)

    assert feed.requests == [["2330", "2317"], ["2330", "2317"]]
    assert status.stale_stock_ids == {"2330", "2317"}
    assert status.stats.stale_market_data_count == 2
    assert status.stats.errors == ["Failed to fetch realtime market data: MIS unreachable"] * 2


async def test_a_fresh_quote_is_not_asked_for_again_and_clears_the_stale_mark(tmp_path) -> None:
    status = run_status()
    fresh = Stock(stock_id="2330", realtime_bar=Ohlcv(ts=NOW, close=100))
    stale = Stock(stock_id="2317", realtime_bar=Ohlcv(ts=NOW - timedelta(minutes=30), close=100))
    status.stale_stock_ids = {"2317"}
    feed = QuoteFeed(daily_close_at=NOW, quote_at=NOW)

    await quote_feed(feed, tmp_path).execute([fresh, stale], status)

    assert fresh.realtime_bar == Ohlcv(ts=NOW, close=100)
    assert stale.realtime_bar is not None and stale.realtime_bar.close == 101
    assert status.stale_stock_ids == set()
