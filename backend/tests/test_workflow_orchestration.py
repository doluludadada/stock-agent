from datetime import datetime, timedelta

import pytest
from support.harness import FRESH, MARKET_CLOSED, MARKET_OPEN, STALE, build_harness, falling_history, rising_history

from a_domain.model.market.stock import Stock
from a_domain.types.enums import AiAnalysisFocus, SignalSource, TradeAction, WatchlistType


def stock_ids(stocks: list[Stock]) -> list[str]:
    return [stock.stock_id for stock in stocks]


# ------------------------------- Menu 1: Full Cycle ------------------------------- #


@pytest.mark.asyncio
async def test_full_cycle_saves_only_survivors_as_technical_and_never_orders() -> None:
    harness = build_harness(now=MARKET_OPEN, market_open=True)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", falling_history(100.0), realtime_price=100.0)

    status = await harness.run_menu("1")

    assert stock_ids(status.survivors) == ["2330"]
    assert harness.watchlist.rows == [("2330", WatchlistType.TECHNICAL)]
    assert [(signal.stock_id, signal.action) for signal in harness.signals.saved] == [("2330", TradeAction.BUY)]
    assert harness.ai.analysed_stock_ids == ["2330"]
    assert harness.broker.placed == []
    assert status.stats.orders_submitted == 0

    await harness.run_menu("3")

    assert [(order.stock_id, order.action) for order in harness.broker.placed] == [("2330", TradeAction.BUY)]


# ------------------------------ Menu 2: Social Buzz ------------------------------- #


@pytest.mark.asyncio
async def test_buzz_scan_persists_only_technical_survivors() -> None:
    harness = build_harness()
    hot = harness.config.collect_rules.buzz_min_engagement
    harness.list_stock("2603", falling_history(50.0), realtime_price=50.0)
    harness.list_stock("1101", rising_history(10.0), realtime_price=10.0)
    harness.discuss("2603", mentions=1, engagement=hot)
    harness.discuss("1101", mentions=1, engagement=hot)

    status = await harness.run_menu("2")

    assert stock_ids(status.buzz_stocks) == ["2603", "1101"]
    assert set(harness.prices.history_requests) == {"2603", "1101"}
    assert stock_ids(status.survivors) == ["2603"], "the Buzz strategy, not the trend strategy, decides survivors"
    assert harness.watchlist.rows == [("2603", WatchlistType.BUZZ)]
    assert [(call.stock_id, call.focus) for call in harness.ai.calls] == [("2603", AiAnalysisFocus.MOMENTUM)]


@pytest.mark.asyncio
async def test_buzz_scan_never_analyses_stocks_below_both_buzz_thresholds() -> None:
    harness = build_harness()
    rules = harness.config.collect_rules
    for stock_id in ("2330", "2317", "2454"):
        harness.list_stock(stock_id, rising_history(100.0), realtime_price=100.0)
    harness.discuss("2330", mentions=rules.buzz_min_mentions, engagement=0)
    harness.discuss("2317", mentions=1, engagement=rules.buzz_min_engagement)
    harness.discuss("2454", mentions=rules.buzz_min_mentions - 1, engagement=rules.buzz_min_engagement - 1)

    status = await harness.run_menu("2")

    assert stock_ids(status.buzz_stocks) == ["2330", "2317"]
    assert (status.stats.buzz_scanned, status.stats.buzz_qualified) == (3, 2)
    assert set(harness.prices.history_requests) == {"2330", "2317"}
    assert set(harness.news.requested) == {"2330", "2317"}
    assert set(harness.ai.analysed_stock_ids) == {"2330", "2317"}


@pytest.mark.parametrize(
    ("now", "market_open", "quote_age", "buy_signals", "orders"),
    [(MARKET_OPEN, True, FRESH, ["2330"], ["2330"]), (MARKET_CLOSED, False, FRESH, ["2330"], []), (MARKET_OPEN, True, STALE, [], [])],
    ids=["open-and-fresh", "market-closed", "stale-quote"],
)
@pytest.mark.asyncio
async def test_buzz_scan_orders_only_when_market_is_open_and_quote_is_fresh(
    now: datetime, market_open: bool, quote_age: timedelta, buy_signals: list[str], orders: list[str]
) -> None:
    harness = build_harness(now=now, market_open=market_open)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0, realtime_age=quote_age)
    harness.discuss("2330", mentions=1, engagement=harness.config.collect_rules.buzz_min_engagement)

    status = await harness.run_menu("2")

    assert [signal.stock_id for signal in harness.signals.saved if signal.action == TradeAction.BUY] == buy_signals
    assert [order.stock_id for order in harness.broker.placed] == orders
    assert status.stats.orders_submitted == len(orders)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Product bug: BuzzScanner extends articles on the Stock object that the stock provider caches (TaiwanStockProvider "
        "keeps it for 6 hours) instead of a copy, so a second Buzz scan in one CLI session prompts the AI with the "
        "previous scan's discussions."
    ),
)
@pytest.mark.asyncio
async def test_second_buzz_scan_in_a_session_prompts_only_current_discussions() -> None:
    harness = build_harness()
    hot = harness.config.collect_rules.buzz_min_engagement
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.discuss("2330", mentions=1, engagement=hot, title="morning thread")
    await harness.run_menu("2")
    harness.social.articles.clear()
    harness.discuss("2330", mentions=1, engagement=hot, title="afternoon thread")

    await harness.run_menu("2")

    second_prompt = harness.ai.calls[-1].prompt
    assert "afternoon thread" in second_prompt
    assert "morning thread" not in second_prompt


# ---------------------------- Menu 3: Intraday Trading ---------------------------- #


@pytest.mark.asyncio
async def test_intraday_loads_held_positions_and_active_watchlist() -> None:
    harness = build_harness()
    for stock_id in ("2330", "2317", "2454"):
        harness.list_stock(stock_id, rising_history(100.0), realtime_price=100.0)
    harness.hold("2330", quantity=1000, average_cost=95.0)
    harness.watch("2330", WatchlistType.TECHNICAL)
    harness.watch("2317", WatchlistType.BUZZ)

    status = await harness.run_menu("3")

    assert status.stats.total_scanned == 2
    assert sorted(harness.ai.analysed_stock_ids) == ["2317", "2330"], "2330 is held and watched but analysed once"
    assert sorted(order.stock_id for order in harness.broker.placed) == ["2317", "2330"]


@pytest.mark.asyncio
async def test_intraday_places_no_order_for_a_stale_quote() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0, realtime_age=FRESH)
    harness.list_stock("2317", rising_history(100.0), realtime_price=100.0, realtime_age=STALE)
    harness.watch("2330", WatchlistType.TECHNICAL)
    harness.watch("2317", WatchlistType.TECHNICAL)

    status = await harness.run_menu("3")

    assert status.stale_stock_ids == {"2317"}
    assert [order.stock_id for order in harness.broker.placed] == ["2330"]


@pytest.mark.parametrize(
    ("now", "market_open", "orders"), [(MARKET_OPEN, True, ["2330"]), (MARKET_CLOSED, False, [])], ids=["market-open", "market-closed"]
)
@pytest.mark.asyncio
async def test_order_execution_skips_closed_market_orders(now: datetime, market_open: bool, orders: list[str]) -> None:
    harness = build_harness(now=now, market_open=market_open)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.watch("2330", WatchlistType.TECHNICAL)

    status = await harness.run_menu("3")

    assert [(signal.stock_id, signal.action) for signal in harness.signals.saved] == [("2330", TradeAction.BUY)]
    assert [order.stock_id for order in harness.broker.placed] == orders
    assert status.stats.orders_submitted == len(orders)


# ------------------------- Menu 4: Analyse Specific Stocks ------------------------ #


@pytest.mark.asyncio
async def test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", falling_history(100.0), realtime_price=100.0)

    status = await harness.run_menu("4", stock_ids="2330 2317")

    passed, failed = status.manual_stocks
    assert stock_ids(status.manual_stocks) == ["2330", "2317"]
    assert stock_ids(status.survivors) == ["2330"]
    assert failed.hard_failures
    assert harness.news.requested == ["2330", "2317"]
    assert harness.ai.analysed_stock_ids == ["2330", "2317"]
    assert passed.composite_score is not None
    assert failed.composite_score is not None
    assert harness.watchlist.rows == []
    assert harness.signals.saved == []
    assert harness.broker.placed == []


@pytest.mark.parametrize(
    ("add_to_watchlist", "rows"),
    [(True, [("2330", WatchlistType.MANUAL), ("2317", WatchlistType.MANUAL)]), (False, [])],
    ids=["confirmed", "declined"],
)
@pytest.mark.asyncio
async def test_specific_stock_watchlist_prompt_writes_only_manual_rows(
    add_to_watchlist: bool, rows: list[tuple[str, WatchlistType]]
) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", falling_history(100.0), realtime_price=100.0)

    status = await harness.run_menu("4", stock_ids="2330 2317", add_to_watchlist=add_to_watchlist)

    assert harness.watchlist.rows == rows
    assert stock_ids(status.survivors) == ["2330"]
    assert harness.signals.saved == []
    assert harness.broker.placed == []


@pytest.mark.asyncio
async def test_confirmed_manual_buy_sends_one_manual_signal_to_the_broker() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", falling_history(100.0), realtime_price=98.0)

    await harness.run_menu("4", stock_ids="2330 2317", buy={"2317"})

    [signal] = harness.signals.saved
    assert (signal.stock_id, signal.action, signal.source) == ("2317", TradeAction.BUY, SignalSource.MANUAL)
    assert signal.quantity > 0
    assert [(order.stock_id, order.action, order.quantity, order.limit_price) for order in harness.broker.placed] == [
        ("2317", TradeAction.BUY, signal.quantity, 98.0)
    ]
    assert harness.watchlist.rows == []
