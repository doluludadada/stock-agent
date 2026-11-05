from datetime import datetime, timedelta

import pytest
from pydantic import SecretStr
from support.harness import (
    FRESH,
    MARKET_CLOSED,
    MARKET_OPEN,
    STALE,
    CliHarness,
    build_harness,
    falling_history,
    harness_config,
    rising_history,
)

from a_domain.model.market.article import Article
from a_domain.model.market.stock import Stock
from a_domain.types.enums import (
    AiAnalysisFocus,
    ExecutionProvider,
    InformationSource,
    OrderMode,
    OrderStatus,
    SignalSource,
    SystemEnvironment,
    TradeAction,
    WatchlistType,
)
from a_domain.types.ids import new_run_id
from b_application.config.app_config import AppConfig
from b_application.config.trading_config import TradingConfig


def stock_ids(stocks: list[Stock]) -> list[str]:
    return [stock.stock_id for stock in stocks]


# ------------------------------- Menu 1: Full Cycle ------------------------------- #


@pytest.mark.asyncio
async def test_full_cycle_saves_only_survivors_as_technical_and_never_orders() -> None:
    harness = build_harness(now=MARKET_OPEN)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", falling_history(100.0), realtime_price=100.0)

    status = await harness.run_menu("1")

    assert stock_ids(status.survivors) == ["2330"]
    assert harness.watchlist.rows == [("2330", WatchlistType.TECHNICAL)]
    assert [(signal.stock_id, signal.action) for signal in harness.journal.signals] == [("2330", TradeAction.BUY)]
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
    ("now", "quote_age", "buy_signals", "orders"),
    [(MARKET_OPEN, FRESH, ["2330"], ["2330"]), (MARKET_CLOSED, FRESH, ["2330"], []), (MARKET_OPEN, STALE, [], [])],
    ids=["open-and-fresh", "market-closed", "stale-quote"],
)
@pytest.mark.asyncio
async def test_buzz_scan_orders_only_when_market_is_open_and_quote_is_fresh(
    now: datetime, quote_age: timedelta, buy_signals: list[str], orders: list[str]
) -> None:
    harness = build_harness(now=now)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0, realtime_age=quote_age)
    harness.discuss("2330", mentions=1, engagement=harness.config.collect_rules.buzz_min_engagement)

    status = await harness.run_menu("2")

    assert [signal.stock_id for signal in harness.journal.signals if signal.action == TradeAction.BUY] == buy_signals
    assert [order.stock_id for order in harness.broker.placed] == orders
    assert status.stats.orders_submitted == len(orders)


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
async def test_one_runs_buys_risk_a_share_of_the_equity_best_score_first_until_the_cash_runs_out() -> None:
    harness = build_harness()
    ai_scores = {"1101": 92, "2317": 98, "2330": 88, "2454": 96, "2603": 90, "3008": 94}

    for stock_id, ai_score in ai_scores.items():
        harness.list_stock(stock_id, rising_history(100.0), realtime_price=100.0)
        harness.watch(stock_id, WatchlistType.TECHNICAL)
        harness.ai.scores[stock_id] = ai_score

    await harness.run_menu("3")

    # 2% of the 1,000,000 equity over the 10 NT$ a share loses at the stop is 2000 shares, 200,285 with the fee.
    # Four fit; the fifth gets what the 198,860 left pays for, fee included; the sixth gets none.
    decisions = [(signal.stock_id, signal.action, signal.quantity) for signal in harness.journal.signals]
    assert decisions == [
        ("2317", TradeAction.BUY, 2000),
        ("2454", TradeAction.BUY, 2000),
        ("3008", TradeAction.BUY, 2000),
        ("1101", TradeAction.BUY, 2000),
        ("2603", TradeAction.BUY, 1985),
        ("2330", TradeAction.HOLD, 0),
    ]
    buys = [(stock_id, quantity) for stock_id, action, quantity in decisions if action == TradeAction.BUY]
    assert [order.stock_id for order in harness.broker.placed] == [stock_id for stock_id, _ in buys]
    assert sum(100 * quantity + max(20, int(100 * quantity * 0.001425)) for _, quantity in buys) == 999_922 <= 1_000_000


@pytest.mark.asyncio
async def test_a_held_position_at_its_quote_counts_toward_the_equity_each_buy_risks_a_share_of() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", rising_history(100.0), realtime_price=100.0)
    harness.hold("2330", quantity=1000, average_cost=95.0)
    harness.watch("2317", WatchlistType.TECHNICAL)

    await harness.run_menu("3")

    # Equity is the 1,000,000 cash plus 1000 held shares at their 100 quote; 2% of it over the 10 NT$ stop is 2200 shares.
    assert [(order.stock_id, order.action, order.quantity) for order in harness.broker.placed] == [
        ("2317", TradeAction.BUY, 2200),
        ("2330", TradeAction.BUY, 2200),
    ]


@pytest.mark.asyncio
async def test_intraday_analyses_unblocked_candidates_with_history_and_decides_on_survivors_and_held_stocks() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", rising_history(100.0), realtime_price=100.0, realtime_age=STALE)
    harness.list_stock("3008", [], realtime_price=100.0)
    harness.list_stock("2454", falling_history(100.0), realtime_price=100.0)
    harness.list_stock("1101", falling_history(100.0), realtime_price=100.0)
    harness.list_stock("2603", rising_history(100.0), realtime_price=100.0)
    harness.hold("2330", quantity=1000, average_cost=120.0)
    harness.hold("3008", quantity=1000, average_cost=95.0)
    harness.hold("1101", quantity=1000, average_cost=95.0)
    for stock_id in ("2317", "2454", "2603"):
        harness.watch(stock_id, WatchlistType.TECHNICAL)

    status = await harness.run_menu("3")

    assert (status.stats.total_scanned, status.risk_blocked_stock_ids, status.stale_stock_ids) == (6, {"2330"}, {"2317"})
    assert sorted(harness.prices.history_requests) == ["1101", "2454", "2603", "3008"], (
        "a stop-loss sale and a stale quote are not analysed"
    )
    assert status.stats.passed_technical == 1, "a stock without daily history gets no technical verdict"
    assert stock_ids(status.survivors) == ["2603", "1101"], "the held stock that failed still gets its exit decided"
    assert sorted(harness.ai.analysed_stock_ids) == ["1101", "2603"], "a held stock that fails the strategy, not one without history"
    assert sorted(signal.stock_id for signal in harness.journal.signals) == ["1101", "2330", "2603"]


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


@pytest.mark.parametrize(("now", "orders"), [(MARKET_OPEN, ["2330"]), (MARKET_CLOSED, [])], ids=["market-open", "market-closed"])
@pytest.mark.asyncio
async def test_order_execution_skips_closed_market_orders(now: datetime, orders: list[str]) -> None:
    harness = build_harness(now=now)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.watch("2330", WatchlistType.TECHNICAL)

    status = await harness.run_menu("3")

    assert [(signal.stock_id, signal.action) for signal in harness.journal.signals] == [("2330", TradeAction.BUY)]
    assert [order.stock_id for order in harness.broker.placed] == orders
    assert status.stats.orders_submitted == len(orders)


@pytest.mark.asyncio
async def test_intraday_fetches_each_candidates_news_and_gives_it_to_the_ai() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.watch("2330", WatchlistType.TECHNICAL)
    harness.news.articles["2330"] = [
        Article(
            stock_id="2330",
            source=InformationSource.NEWS_MEDIA,
            title="TSMC raises its full-year revenue outlook",
            content="Revenue guidance rises on AI server demand. " * 6,
            published_at=harness.clock.now() - timedelta(hours=2),
            fetched_at=harness.clock.now(),
        )
    ]

    await harness.run_menu("3")

    assert harness.news.requested == ["2330"]
    assert [(call.stock_id, "TSMC raises its full-year revenue outlook" in call.prompt) for call in harness.ai.calls] == [
        ("2330", True)
    ]


@pytest.mark.asyncio
async def test_intraday_records_each_decision_and_the_brokers_answer_to_its_order() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.watch("2330", WatchlistType.TECHNICAL)

    status = await harness.run_menu("3")

    run_id = status.stats.run_id
    [signal] = harness.journal.signals
    [order] = harness.journal.orders.values()
    assert (signal.stock_id, signal.action, harness.journal.signal_runs[signal.decision_id]) == ("2330", TradeAction.BUY, run_id)
    assert (order.run_id, order.decision_id, order.status, order.filled_quantity) == (
        run_id,
        signal.decision_id,
        OrderStatus.FILLED,
        signal.quantity,
    )
    assert harness.journal.runs[run_id].orders_submitted == 1


@pytest.mark.asyncio
async def test_a_run_record_names_its_strategy_and_ai_model_and_counts_its_fills() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.watch("2330", WatchlistType.TECHNICAL)
    ai = harness.config.ai
    saved = harness.technical_settings.saved[harness.config.technical.owner_id]

    status = await harness.run_menu("3")

    record = harness.journal.runs[status.stats.run_id]
    assert (record.technical_strategy_id, record.ai_model, record.orders_filled) == (
        saved.active_strategy.strategy_id,
        ai.available_models[ai.active_model],
        1,
    )


@pytest.mark.asyncio
async def test_intraday_buys_holds_and_sells_manually_watched_stocks_on_their_composite_score() -> None:
    config = harness_config()
    config.analysis = config.analysis.model_copy(update={"min_combined_score_buy": 70, "max_combined_score_sell": 50})
    harness = build_harness(config=config)
    for stock_id, ai_score in {"2317": 90, "2454": 40, "2330": 10}.items():
        harness.list_stock(stock_id, rising_history(100.0), realtime_price=100.0)
        harness.watch(stock_id, WatchlistType.MANUAL)
        harness.ai.scores[stock_id] = ai_score
    harness.hold("2330", quantity=1000, average_cost=95.0)

    await harness.run_menu("3")

    # Composite = (technical 90 + AI) / 2, so 90 buys, 65 holds, and the held stock's 50 sells at the 50 sell threshold.
    assert [(signal.stock_id, signal.action) for signal in harness.journal.signals] == [
        ("2317", TradeAction.BUY),
        ("2454", TradeAction.HOLD),
        ("2330", TradeAction.SELL),
    ]
    assert [(order.stock_id, order.action) for order in harness.broker.placed] == [
        ("2317", TradeAction.BUY),
        ("2330", TradeAction.SELL),
    ]
    assert harness.broker.placed[-1].quantity == 1000


@pytest.mark.parametrize("menu", ["1", "3"], ids=["full-cycle", "intraday"])
@pytest.mark.asyncio
async def test_an_automatic_buy_of_a_manually_watched_stock_is_a_combined_decision_never_a_manual_one(menu: str) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.watch("2330", WatchlistType.MANUAL)

    await harness.run_menu(menu)

    assert [(signal.stock_id, signal.action, signal.source) for signal in harness.journal.signals] == [
        ("2330", TradeAction.BUY, SignalSource.COMBINED)
    ]


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
    assert harness.journal.signals == []
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
    assert harness.journal.signals == []
    assert harness.broker.placed == []


@pytest.mark.asyncio
async def test_confirmed_manual_buy_sends_one_manual_signal_to_the_broker() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", falling_history(100.0), realtime_price=98.0)

    await harness.run_menu("4", stock_ids="2330 2317", buy={"2317"})

    [signal] = harness.journal.signals
    assert (signal.stock_id, signal.action, signal.source) == ("2317", TradeAction.BUY, SignalSource.MANUAL)
    assert signal.quantity > 0
    assert [(order.stock_id, order.action, order.quantity, order.limit_price) for order in harness.broker.placed] == [
        ("2317", TradeAction.BUY, signal.quantity, 98.0)
    ]
    assert harness.watchlist.rows == []


@pytest.mark.asyncio
async def test_a_confirmed_manual_buy_is_sent_even_below_the_automatic_buy_threshold() -> None:
    harness = build_harness()
    harness.list_stock("2317", falling_history(100.0), realtime_price=98.0)
    harness.ai.scores["2317"] = 10

    status = await harness.run_menu("4", stock_ids="2317", buy={"2317"})

    [analysed] = status.manual_stocks
    assert analysed.composite_score is not None and analysed.composite_score < harness.config.analysis.min_combined_score_buy
    assert [(signal.stock_id, signal.action, signal.source) for signal in harness.journal.signals] == [
        ("2317", TradeAction.BUY, SignalSource.MANUAL)
    ]
    assert [(order.stock_id, order.action) for order in harness.broker.placed] == [("2317", TradeAction.BUY)]


# ------------------------------ Caller-named run ids ------------------------------ #


@pytest.mark.asyncio
@pytest.mark.parametrize(("workflow", "arguments"), [("run_full_cycle", ()), ("analyse_specific_stocks", (["2330"],))])
async def test_a_workflow_started_under_a_named_run_id_records_under_it(workflow: str, arguments: tuple) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    run_id = new_run_id()

    status = await getattr(harness.runtime.pipeline, workflow)(*arguments, run_id=run_id)

    assert status.stats.run_id == run_id
    assert list(harness.journal.runs) == [run_id]
    assert {harness.journal.signal_runs[signal.decision_id] for signal in harness.journal.signals} <= {run_id}


# --------------------------- Every workflow that decides -------------------------- #


def wanted_by_every_workflow(config: AppConfig | None = None) -> CliHarness:
    """2330 is listed, rising, on the TECHNICAL watchlist and trending, so menus 1, 2 and 3 each decide to BUY it."""
    harness = build_harness(config=config)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.watch("2330", WatchlistType.TECHNICAL)
    harness.discuss("2330", mentions=1, engagement=harness.config.collect_rules.buzz_min_engagement)
    return harness


@pytest.mark.parametrize(
    ("environment", "provider", "mode", "placed", "outcome"),
    [
        (SystemEnvironment.DEV, ExecutionProvider.MOCK, OrderMode.DISABLED, [], (OrderStatus.REJECTED, "ORDER_MODE_DISABLED")),
        (SystemEnvironment.DEV, ExecutionProvider.MOCK, OrderMode.MOCK_ONLY, ["2330"], (OrderStatus.FILLED, "")),
        (SystemEnvironment.LIVE, ExecutionProvider.SHIOAJI, OrderMode.LIVE, ["2330"], (OrderStatus.FILLED, "")),
    ],
    ids=["disabled", "mock-only", "live"],
)
@pytest.mark.parametrize("menu", ["2", "3"], ids=["buzz", "intraday"])
@pytest.mark.asyncio
async def test_buzz_and_intraday_send_an_order_only_when_the_order_mode_allows_it(
    menu: str,
    environment: SystemEnvironment,
    provider: ExecutionProvider,
    mode: OrderMode,
    placed: list[str],
    outcome: tuple[OrderStatus, str],
) -> None:
    config = harness_config()
    config.environment = environment
    config.trading = TradingConfig(execution_provider=provider, order_mode=mode)
    config.shioaji = config.shioaji.model_copy(
        update={"simulation": True, "api_key": SecretStr("key"), "secret_key": SecretStr("secret")}
    )
    harness = wanted_by_every_workflow(config)

    await harness.run_menu(menu)

    [order] = harness.journal.orders.values()
    assert [order.stock_id for order in harness.broker.placed] == placed
    assert (order.stock_id, order.status, (order.reason or "").split(":")[0]) == ("2330", *outcome)


@pytest.mark.parametrize(
    ("menu", "answers"),
    [("1", {}), ("2", {}), ("3", {}), ("4", {"stock_ids": "2330", "buy": {"2330"}})],
    ids=["full-cycle", "buzz", "intraday", "manual-buy"],
)
@pytest.mark.asyncio
async def test_every_workflow_that_decides_hands_each_decision_to_the_knowledge_repository(menu: str, answers: dict) -> None:
    harness = wanted_by_every_workflow()

    await harness.run_menu(menu, **answers)

    assert [(signal.stock_id, signal.action) for signal in harness.journal.signals] == [("2330", TradeAction.BUY)]
    assert [(stock_id, signal.decision_id) for stock_id, signal in harness.knowledge.decisions] == [
        (signal.stock_id, signal.decision_id) for signal in harness.journal.signals
    ]
