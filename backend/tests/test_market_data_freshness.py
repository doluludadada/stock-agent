from datetime import date, datetime, time, timedelta

import pytest
from support.settings import shipped_config
from trading_stack import SilentLogger, run_stats

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.types.enums import MarketType
from b_application.config.app_config import AppConfig
from b_application.config.market_data_config import MarketHoursConfig
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.collect.realtime_quote_feed import RealtimeQuoteFeed
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)
MISSING_FRIDAY = (
    "Daily history lacks the 2026-10-16 session for 2/2 stocks (2317, 2330): no TWSE stock has it, so TWSE has not "
    "published it yet, it was an exchange holiday, or none of these stocks traded. Their analysis ends at an earlier close."
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
    config = shipped_config(tmp_path)
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
    stats = run_stats()
    feed = QuoteFeed(daily_close_at=NOW - timedelta(days=days_old), quote_at=NOW)

    stock = Stock(stock_id="2330")

    analysable = await collector(feed, tmp_path).execute([stock], 1, stats)

    assert stats.stale_market_data_count == blocked
    assert bool(stock.ohlcv) is not bool(blocked)
    assert analysable == ([] if blocked else [stock])


async def test_a_skipped_stock_gets_no_history_and_is_not_analysed(tmp_path) -> None:
    feed = QuoteFeed(daily_close_at=NOW, quote_at=NOW)
    kept, skipped = Stock(stock_id="2330"), Stock(stock_id="2317")

    analysable = await collector(feed, tmp_path).execute([kept, skipped], 1, run_stats(), skip=frozenset({"2317"}))

    assert (analysable, skipped.ohlcv) == ([kept], [])


@pytest.mark.parametrize(("minutes_old", "stale"), [(15, False), (16, True)])
async def test_realtime_quotes_use_the_minute_limit_not_the_day_limit(tmp_path, minutes_old: int, stale: bool) -> None:
    feed = QuoteFeed(daily_close_at=NOW, quote_at=NOW - timedelta(minutes=minutes_old))

    stale_stock_ids = await quote_feed(feed, tmp_path).execute([Stock(stock_id="2330")], set(), run_stats())

    assert ("2330" in stale_stock_ids) is stale


@pytest.mark.parametrize(("last_session", "errors"), [(date(2026, 10, 16), []), (date(2026, 10, 15), [MISSING_FRIDAY])])
async def test_history_without_the_last_settled_session_is_a_run_error(tmp_path, last_session: date, errors: list[str]) -> None:
    stats = run_stats()
    feed = QuoteFeed(daily_close_at=datetime.combine(last_session, time(13, 30), TAIWAN_TIMEZONE), quote_at=NOW)
    stocks = [Stock(stock_id="2330"), Stock(stock_id="2317")]

    await collector(feed, tmp_path).execute(stocks, 1, stats)

    assert stats.errors == errors
    assert all(stock.ohlcv for stock in stocks)


class SessionFeed:
    def __init__(self, sessions: dict[str, date]) -> None:
        self._sessions = sessions

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        return {
            stock_id: [Ohlcv(ts=datetime.combine(session, time(13, 30), TAIWAN_TIMEZONE), open=1, high=1, low=1, close=1, volume=1)]
            for stock_id, session in self._sessions.items()
        }


FRIDAY, THURSDAY = date(2026, 10, 16), date(2026, 10, 15)
TWSE_UNPUBLISHED = (
    "Daily history lacks the 2026-10-16 session for 2/3 stocks (1538, 2330): no TWSE stock has it, so TWSE has not "
    "published it yet, it was an exchange holiday, or none of these stocks traded. Their analysis ends at an earlier close."
)


@pytest.mark.parametrize(
    ("sessions", "errors"),
    [
        ({"2330": FRIDAY, "1538": THURSDAY, "6488": FRIDAY}, []),
        ({"2330": THURSDAY, "1538": THURSDAY, "6488": FRIDAY}, [TWSE_UNPUBLISHED]),
    ],
    ids=["a stock without a trade that session", "TPEX published and TWSE not yet"],
)
async def test_a_session_is_missing_only_when_none_of_an_exchanges_stocks_has_it(
    tmp_path, sessions: dict[str, date], errors: list[str]
) -> None:
    stats = run_stats()
    stocks = [Stock(stock_id="2330"), Stock(stock_id="1538"), Stock(stock_id="6488", market=MarketType.TPEX)]

    await MarketDataCollector(
        ohlcv_provider=SessionFeed(sessions),
        market_clock=ClockAt(MarketHoursConfig()),
        config=freshness_config(tmp_path),
        logger=SilentLogger(),
    ).execute(stocks, 1, stats)

    assert stats.errors == errors
    assert all(stock.ohlcv for stock in stocks)


class FailingQuoteFeed:
    def __init__(self) -> None:
        self.requests: list[list[str]] = []

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        self.requests.append([stock.stock_id for stock in stocks])
        raise ConnectionError("MIS unreachable")


async def test_a_failed_quote_fetch_blocks_every_asked_stock_once(tmp_path) -> None:
    stats = run_stats()
    feed = FailingQuoteFeed()
    stocks = [Stock(stock_id="2330"), Stock(stock_id="2317"), Stock(stock_id="2330")]

    stale_stock_ids = await quote_feed(feed, tmp_path).execute(stocks, set(), stats)
    stale_stock_ids = await quote_feed(feed, tmp_path).execute(stocks, stale_stock_ids, stats)

    assert feed.requests == [["2330", "2317"], ["2330", "2317"]]
    assert stale_stock_ids == {"2330", "2317"}
    assert stats.stale_market_data_count == 2
    assert stats.errors == ["Failed to fetch realtime market data: MIS unreachable"] * 2


async def test_a_fresh_quote_is_not_asked_for_again_and_clears_the_stale_mark(tmp_path) -> None:
    fresh = Stock(stock_id="2330", realtime_bar=Ohlcv(ts=NOW, close=100))
    stale = Stock(stock_id="2317", realtime_bar=Ohlcv(ts=NOW - timedelta(minutes=30), close=100))
    feed = QuoteFeed(daily_close_at=NOW, quote_at=NOW)

    stale_stock_ids = await quote_feed(feed, tmp_path).execute([fresh, stale], {"2317"}, run_stats())

    assert fresh.realtime_bar == Ohlcv(ts=NOW, close=100)
    assert stale.realtime_bar is not None and stale.realtime_bar.close == 101
    assert stale_stock_ids == set()
