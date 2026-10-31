from datetime import date, datetime, time, timedelta
from uuid import uuid4

import pytest

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.account_snapshot import AccountSnapshot
from a_domain.rules.trading.decision import DecisionSkipRule
from a_domain.rules.trading.exit import BlockedStockRule, StopLossQuoteRule
from a_domain.rules.trading.valuation import LatestMarkRule, PriceHistoryStartRule
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)
QUOTE = Ohlcv(ts=NOW, open=100, high=100, low=100, close=100, volume=1000)
DAILY = Ohlcv(ts=NOW - timedelta(days=3), open=98, high=98, low=98, close=98, volume=1000)


@pytest.mark.parametrize(
    ("stock", "risk_blocked", "stale", "skip"),
    [
        (Stock(stock_id="2330", realtime_bar=QUOTE, composite_score=80), set(), set(), None),
        (Stock(stock_id="2330", ohlcv=[DAILY], composite_score=80), set(), set(), None),
        (Stock(stock_id="2330", realtime_bar=QUOTE, composite_score=80), {"2330"}, {"2330"}, "Risk blocked"),
        (Stock(stock_id="2330", realtime_bar=QUOTE, composite_score=80), {"1101"}, {"2330"}, "Market data is stale"),
        (Stock(stock_id="2330", realtime_bar=QUOTE), set(), set(), "Composite score unavailable"),
        (Stock(stock_id="2330", composite_score=80), set(), set(), "No price"),
    ],
)
def test_a_watchlist_stock_is_decided_only_when_not_sold_fresh_scored_and_priced(
    stock: Stock, risk_blocked: set[str], stale: set[str], skip: str | None
) -> None:
    assert DecisionSkipRule(blocked_rule=BlockedStockRule()).apply(stock, risk_blocked, stale) == skip


@pytest.mark.parametrize(
    ("stock", "risk_blocked", "stale", "skip"),
    [
        (Stock(stock_id="2330", realtime_bar=QUOTE), set(), set(), None),
        (Stock(stock_id="2330", realtime_bar=QUOTE), set(), {"2330"}, "Market data is stale"),
        (Stock(stock_id="2330", ohlcv=[DAILY]), set(), set(), "Realtime bar unavailable"),
        (Stock(stock_id="2330", realtime_bar=QUOTE), {"2330"}, set(), "Risk blocked"),
    ],
)
def test_a_stop_loss_is_checked_only_once_and_only_on_a_fresh_realtime_quote(
    stock: Stock, risk_blocked: set[str], stale: set[str], skip: str | None
) -> None:
    assert StopLossQuoteRule(blocked_rule=BlockedStockRule()).apply(stock, risk_blocked, stale) == skip


def snapshot_taken(day: date) -> AccountSnapshot:
    return AccountSnapshot(
        taken_at=datetime(day.year, day.month, day.day, 13, 30, tzinfo=TAIWAN_TIMEZONE), run_id=uuid4(), order_id=uuid4(), cash=0
    )


@pytest.mark.parametrize(
    ("snapshots", "start"),
    [
        ([], date(2026, 10, 9)),
        ([snapshot_taken(date(2026, 10, 12))], date(2026, 10, 9)),
        ([snapshot_taken(date(2026, 9, 1))], date(2026, 9, 1)),
    ],
)
def test_daily_prices_reach_back_to_the_history_window_or_the_first_fill(snapshots: list[AccountSnapshot], start: date) -> None:
    rule = PriceHistoryStartRule(history_days=10)

    assert rule.apply(NOW, snapshots, lambda moment: moment.astimezone(TAIWAN_TIMEZONE).date()) == datetime.combine(
        start, time.min, tzinfo=TAIWAN_TIMEZONE
    )


def test_a_stock_is_marked_at_its_realtime_quote_else_at_its_last_daily_close() -> None:
    daily = {"2330": [DAILY], "2317": [DAILY.model_copy(update={"close": 97}), DAILY], "1101": []}

    marks = LatestMarkRule().apply(daily, {"2330": QUOTE})

    assert {stock_id: mark.close for stock_id, mark in marks.items()} == {"2330": 100, "2317": 98}
