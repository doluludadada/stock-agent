"""
The monthly ranking followed into the user's mock account, on a real SQLite journal and mock book: a follow sells what
left the ranking and buys what the account lacks at an equal weight, in whole lots, at the price the site orders at now,
through the same order gates as a follow of a run. A ranked stock already held is left alone, so a second follow of the
same decision orders nothing. The account's return since its first follow is read against the benchmark over the same
sessions. Then the Web API's two routes: their feature gates, their refusals, and the mock account as the only broker.
"""

import asyncio
from datetime import date, datetime, time, timedelta

import pytest
from support.harness import MARKET_CLOSED, MEMBER, MEMBER_PASSWORD, CliHarness, build_harness, harness_config
from support.web import ended, serve, write
from test_follow import RealBroker
from test_ranking_rule import revenue
from trading_stack import MONDAY_10_00, TradingStack, bar, open_stack

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account, AccountOpening, Position
from a_domain.rules.trading.follow import FollowReturn, RankingFollowReturnRule, RankingHoldings, RankingHoldingsRule
from a_domain.rules.trading.ranking import ListedHistoryRule, RankedStock, Ranking, RankingHistoryRule
from a_domain.types.enums import (
    Audience,
    ExecutionProvider,
    FeatureVisibility,
    FollowRefusal,
    OrderStatus,
    SignalSource,
    TradeAction,
    Workflow,
)
from b_application.config.app_config import AppConfig
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

pytestmark = pytest.mark.asyncio

SESSIONS = [date(2026, 10, day) for day in (8, 9, 12, 13, 14, 15, 16)]
"""The ranking decides at the close of October 13 and reads September's revenue. The clock stands at Monday the 19th, 10:00."""

CLOSES = {"2330": 100.0, "2317": 50.0, "1101": 30.0, "0050": 186.0}
"""Each stock's close on Friday the 16th, after rising 1 a session: every stock is at its high, so revenue orders them."""

REVENUES = {"2330": (100.0, 200.0), "2317": (100.0, 100.0), "1101": (100.0, 50.0)}
"""August's and September's revenue: 2330 doubled it, 2317 held it, 1101 halved it. The ranking holds the best two."""

RANKING_WINDOWS = {
    "top": 2,
    "high_sessions": 3,
    "traded_value_sessions": 2,
    "revenue_short_months": 1,
    "revenue_long_months": 2,
    "min_traded_value": 0,
    "min_close": 0,
}
FEE_RATE = 0.001425


def close_of(day: date, price: float) -> Ohlcv:
    return bar(datetime.combine(day, time(13, 30), TAIWAN_TIMEZONE), price)


def daily_history() -> dict[str, list[Ohlcv]]:
    return {
        stock_id: [close_of(day, last - len(SESSIONS) + place) for place, day in enumerate(SESSIONS, 1)]
        for stock_id, last in CLOSES.items()
    }


def small_ranking(config: AppConfig) -> None:
    config.ranking = config.ranking.model_copy(update=RANKING_WINDOWS)


def public_site(config: AppConfig) -> None:
    small_ranking(config)
    config.audience = Audience.PUBLIC


async def market(tmp_path, configure=small_ranking, **options) -> TradingStack:
    """The stack with the history and the revenue above, and a fresh quote of each stock at its Friday close."""
    stack = await open_stack(tmp_path, configure=configure, **options)
    stack.quotes.daily.update(daily_history())
    stack.quotes.realtime = {stock_id: bar(MONDAY_10_00 - timedelta(minutes=1), price) for stock_id, price in CLOSES.items()}

    for stock_id, (august, september) in REVENUES.items():
        stack.archive.monthly_revenues[(stock_id, 2026, 8)] = revenue(stock_id, 2026, 8, august)
        stack.archive.monthly_revenues[(stock_id, 2026, 9)] = revenue(stock_id, 2026, 9, september)

    return stack


async def holding(stack: TradingStack, *positions: tuple[str, int, float], cash: float | None = None) -> None:
    """Puts the positions in the mock book, each as stock, shares and average cost, paid from its cash."""
    account = await stack.broker.get_account()

    for stock_id, quantity, average_cost in positions:
        account.buy(stock_id, quantity, price=average_cost, total_cost=quantity * average_cost)

    account.cash = account.cash if cash is None else cash
    await stack.broker.save_account(account, stack.clock.now())


def affordable(budget: float, price: float) -> int:
    """The most shares whose value and fee the budget pays for, as AffordableQuantityRule sizes one share at a time."""
    quantity = int((budget + 1) // (price * (1 + FEE_RATE)))
    return quantity if quantity * price + max(20, int(quantity * price * FEE_RATE)) <= budget else quantity - 1


def ranking_of(*stock_ids: str) -> Ranking:
    stocks = [
        RankedStock(stock_id=stock_id, revenue_acceleration=1, nearness_to_high=1, acceleration_rank=1, nearness_rank=1, score=2)
        for stock_id in stock_ids
    ]
    return Ranking(decided_on=SESSIONS[3], revenue_month=date(2026, 9, 1), universe=3, scored=3, stocks=stocks)


# ----------------------------------- Rules ------------------------------------ #


def test_the_holdings_are_split_into_the_ranked_ones_held_the_ranked_ones_lacking_and_the_ones_that_left() -> None:
    account = Account(
        cash=0, positions=[Position(stock_id=stock_id, quantity=1, average_cost=1) for stock_id in ("2603", "2317", "1101")]
    )

    holdings = RankingHoldingsRule().apply(ranking_of("2330", "2317"), account)

    assert (holdings.held, holdings.lacking, holdings.left) == (["2317"], ["2330"], ["1101", "2603"])
    assert holdings.open == ["1101", "2603", "2330"]
    assert holdings.decided_on == SESSIONS[3]


def test_a_ranking_of_no_stock_sells_nothing() -> None:
    account = Account(cash=0, positions=[Position(stock_id="2317", quantity=1, average_cost=1)])

    assert RankingHoldingsRule().apply(ranking_of(), account) == RankingHoldings(decided_on=SESSIONS[3])


def test_the_return_counts_from_the_close_before_the_first_follow_to_the_last_session_both_curves_reach() -> None:
    history = daily_history()
    monday, tuesday = date(2026, 10, 19), date(2026, 10, 20)
    history["0050"] = [*history["0050"], close_of(monday, 188), close_of(tuesday, 190)]
    listed = ListedHistoryRule().apply(history, {}, lambda stamp: stamp.astimezone(TAIWAN_TIMEZONE).date())
    ranking_history = RankingHistoryRule(daily_limit=0.105).apply(listed, {})
    opening = AccountOpening(initial_cash=1_000_000, opened_at=MONDAY_10_00)
    curve = {monday: Account(cash=990_000), tuesday: Account(cash=1_020_000)}
    rule = RankingFollowReturnRule(benchmark_id="0050")

    followed = rule.apply(monday, opening, curve, ranking_history)
    after_a_trade = rule.apply(tuesday, opening, curve, ranking_history)
    same_day = rule.apply(date(2026, 10, 21), opening, {date(2026, 10, 21): Account(cash=1)}, ranking_history)
    unlisted = RankingFollowReturnRule(benchmark_id="006208").apply(monday, opening, curve, ranking_history)

    assert (followed.since, followed.until, followed.benchmark_id) == (monday, tuesday, "0050")
    assert (followed.account_return, followed.benchmark_return) == (pytest.approx(0.02), pytest.approx(190 / 186 - 1))
    assert (after_a_trade.account_return, after_a_trade.benchmark_return) == (
        pytest.approx(1_020 / 990 - 1),
        pytest.approx(190 / 188 - 1),
    )
    assert same_day == FollowReturn(since=date(2026, 10, 21), benchmark_id="0050")
    assert (unlisted.account_return, unlisted.benchmark_return) == (pytest.approx(0.02), None)


# ------------------------------ Personal site --------------------------------- #


async def test_a_follow_from_an_empty_account_buys_each_ranked_stock_at_an_equal_weight_in_whole_shares(tmp_path) -> None:
    stack = await market(tmp_path)

    before, refusal = await stack.pipeline.load_ranking_follow()
    performance = await stack.pipeline.load_ranking_follow_return()
    status = await stack.pipeline.follow_ranking()

    account = await stack.broker.get_account()
    decisions = await stack.journal.signals_of(status.stats.run_id)
    after, again = await stack.pipeline.load_ranking_follow()
    assert (before.held, before.lacking, before.left, refusal, performance) == ([], ["2330", "2317"], [], None, None)
    assert (status.stats.workflow, status.stats.execution_provider) == (Workflow.RANKING_FOLLOW, ExecutionProvider.MOCK)
    assert [(order.stock_id, order.action, order.status, order.limit_price, order.filled_quantity) for order in status.orders] == [
        ("2330", TradeAction.BUY, OrderStatus.FILLED, 100, affordable(500_000, 100)),
        ("2317", TradeAction.BUY, OrderStatus.FILLED, 50, affordable(500_000, 50)),
    ]
    assert affordable(500_000, 100) == 4992
    assert {decision.source for decision in decisions} == {SignalSource.RANKING}
    assert decisions[0].reason == "Place 1 of the monthly ranking decided at the close of 2026-10-13"
    assert all(order.fee > 0 and order.tax == 0 for order in status.orders)
    assert 0 <= account.cash < 300 and account.stock_ids == {"2330", "2317"}
    assert (after.held, after.lacking, after.left, again) == (["2330", "2317"], [], [], FollowRefusal.NOTHING_TO_FOLLOW)


async def test_a_second_follow_of_the_same_decision_orders_nothing_whatever_the_prices_did(tmp_path) -> None:
    stack = await market(tmp_path)
    first = await stack.pipeline.follow_ranking()
    held = await stack.broker.get_account()
    stack.clock.current = MONDAY_10_00 + timedelta(minutes=30)
    stack.quotes.realtime = {stock_id: bar(stack.clock.current, price * 1.05) for stock_id, price in CLOSES.items()}

    second = await stack.pipeline.follow_ranking()

    assert len(first.orders) == 2
    assert (second.follow_refusal, second.signals, second.orders) == (FollowRefusal.NOTHING_TO_FOLLOW, [], [])
    assert await stack.broker.get_account() == held


async def test_an_account_that_holds_last_months_ranking_sells_what_left_and_buys_only_what_entered(tmp_path) -> None:
    stack = await market(tmp_path)
    await holding(stack, ("2317", 9000, 50.0), ("1101", 15000, 30.0))

    status = await stack.pipeline.follow_ranking()

    account = await stack.broker.get_account()
    sell, buy = status.orders
    proceeds = 15000 * 30 - int(15000 * 30 * FEE_RATE) - int(15000 * 30 * 0.003)
    assert (sell.stock_id, sell.action, sell.status, sell.filled_quantity, sell.limit_price) == (
        "1101",
        TradeAction.SELL,
        OrderStatus.FILLED,
        15000,
        30,
    )
    assert (buy.stock_id, buy.action, buy.status, buy.limit_price) == ("2330", TradeAction.BUY, OrderStatus.FILLED, 100)
    assert buy.filled_quantity == affordable(min(1_000_000 / 2, 100_000 + proceeds), 100) == 4992
    stayed = account.position_for("2317")
    assert stayed is not None and (stayed.quantity, stayed.average_cost) == (9000, 50.0)
    assert account.stock_ids == {"2330", "2317"}


async def test_a_buy_is_sized_from_the_cash_the_account_has_once_the_sales_settle(tmp_path) -> None:
    stack = await market(tmp_path)
    await holding(stack, ("2317", 18000, 50.0))

    status = await stack.pipeline.follow_ranking()

    [buy] = status.orders
    assert (buy.stock_id, buy.status, buy.filled_quantity) == ("2330", OrderStatus.FILLED, affordable(100_000, 100))
    assert affordable(100_000, 100) == 998


async def test_an_account_without_the_cash_for_one_lot_buys_nothing_and_the_run_says_why(tmp_path) -> None:
    stack = await market(tmp_path)
    await holding(stack, cash=60)

    status = await stack.pipeline.follow_ranking()

    holdings, refusal = await stack.pipeline.load_ranking_follow()
    assert (status.signals, status.orders) == ([], [])
    assert [line.split("] ")[1] for line in status.stats.execution_log] == [
        "Not followed now: 2330: its share of the account, 30, buys no lot of 1 at 100.0",
        "Not followed now: 2317: its share of the account, 30, buys no lot of 1 at 50.0",
    ]
    assert (holdings.lacking, refusal) == (["2330", "2317"], None)


async def test_a_stock_without_a_fresh_quote_is_refused_at_the_gate_and_the_next_follow_takes_it(tmp_path) -> None:
    stack = await market(tmp_path)
    del stack.quotes.realtime["2317"]

    first = await stack.pipeline.follow_ranking()
    stack.quotes.realtime["2317"] = bar(MONDAY_10_00 - timedelta(minutes=1), 50)
    second = await stack.pipeline.follow_ranking()

    bought, refused = first.orders
    [retried] = second.orders
    assert (bought.stock_id, bought.status) == ("2330", OrderStatus.FILLED)
    assert (refused.stock_id, refused.status, refused.filled_quantity) == ("2317", OrderStatus.REJECTED, 0)
    assert refused.reason is not None and refused.reason.startswith("STALE_PRICE")
    assert (retried.stock_id, retried.status) == ("2317", OrderStatus.FILLED)
    value_after_the_first = 1_000_000 - bought.fee
    assert retried.filled_quantity == affordable(value_after_the_first / 2, 50)


async def test_a_stock_with_no_price_at_all_gets_no_decision_and_the_run_says_so(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    stack = await market(tmp_path)
    served = stack.quotes.fetch_history
    del stack.quotes.realtime["2317"]

    async def without_2317(stocks: list[Stock], start: datetime, end: datetime) -> dict[str, list[Ohlcv]]:
        return await served([stock for stock in stocks if stock.stock_id != "2317"], start, end)

    monkeypatch.setattr(stack.quotes, "fetch_history", without_2317)

    status = await stack.pipeline.follow_ranking()

    assert [order.stock_id for order in status.orders] == ["2330"]
    assert status.stats.execution_log[-1].endswith("Not followed now: 2317 has neither a realtime quote nor an official close")


async def test_outside_continuous_trading_the_follow_is_refused_and_sends_nothing(tmp_path) -> None:
    stack = await market(tmp_path)
    stack.clock.current = MONDAY_10_00 + timedelta(hours=4)

    holdings, refusal = await stack.pipeline.load_ranking_follow()
    status = await stack.pipeline.follow_ranking()

    assert (holdings.lacking, refusal) == (["2330", "2317"], FollowRefusal.OUTSIDE_FOLLOW_WINDOW)
    assert (status.follow_refusal, status.signals, status.orders) == (FollowRefusal.OUTSIDE_FOLLOW_WINDOW, [], [])


async def test_a_month_without_revenue_ranks_nothing_and_a_follow_of_it_keeps_every_holding(tmp_path) -> None:
    stack = await market(tmp_path)
    stack.archive.monthly_revenues.clear()
    await holding(stack, ("1101", 1000, 30.0))

    holdings, refusal = await stack.pipeline.load_ranking_follow()
    status = await stack.pipeline.follow_ranking()

    assert (holdings, refusal) == (RankingHoldings(decided_on=SESSIONS[3]), FollowRefusal.NOTHING_TO_FOLLOW)
    assert status.orders == [] and (await stack.broker.get_account()).stock_ids == {"1101"}


async def test_the_return_since_the_first_follow_is_read_against_the_benchmark_over_the_same_sessions(tmp_path) -> None:
    stack = await market(tmp_path)
    status = await stack.pipeline.follow_ranking()
    monday, tuesday = date(2026, 10, 19), date(2026, 10, 20)
    on_the_day = await stack.pipeline.load_ranking_follow_return()
    later = {"2330": (101.0, 110.0), "2317": (50.0, 51.0), "1101": (30.0, 30.0), "0050": (188.0, 190.0)}

    for stock_id, closes in later.items():
        stack.quotes.daily[stock_id] = [
            *stack.quotes.daily[stock_id],
            *(close_of(day, price) for day, price in zip((monday, tuesday), closes, strict=True)),
        ]

    stack.clock.current = datetime.combine(tuesday, time(15, 0), TAIWAN_TIMEZONE)
    performance = await stack.pipeline.load_ranking_follow_return()

    cash = (await stack.broker.get_account()).cash
    equity = cash + sum(order.filled_quantity * later[order.stock_id][1] for order in status.orders)
    assert on_the_day == FollowReturn(since=monday, benchmark_id="0050")
    assert performance is not None and (performance.since, performance.until) == (monday, tuesday)
    assert performance.account_return == pytest.approx(equity / 1_000_000 - 1)
    assert performance.benchmark_return == pytest.approx(190 / 186 - 1)


async def test_a_reset_account_has_never_followed(tmp_path) -> None:
    stack = await market(tmp_path)
    await stack.pipeline.follow_ranking()
    stack.clock.current = MONDAY_10_00 + timedelta(minutes=5)
    await stack.pipeline.reset_mock_account(500_000)

    holdings, refusal = await stack.pipeline.load_ranking_follow()

    assert (holdings.held, holdings.lacking, refusal) == ([], ["2330", "2317"], None)
    assert await stack.pipeline.load_ranking_follow_return() is None


async def test_a_follow_on_a_pipeline_built_for_sinopac_never_reaches_it_and_orders_nothing(tmp_path) -> None:
    real = RealBroker()
    stack = await market(tmp_path, real_broker=real, broker=ExecutionProvider.SHIOAJI)

    holdings, _ = await stack.pipeline.load_ranking_follow()
    status = await stack.pipeline.follow_ranking()

    assert holdings.lacking == ["2330", "2317"]
    assert [(order.status, order.filled_quantity) for order in status.orders] == [(OrderStatus.REJECTED, 0)] * 2
    assert all(
        order.reason is not None and order.reason.startswith("BROKER_NOT_CHOSEN: the run chose shioaji") for order in status.orders
    )
    assert (await stack.broker.get_account()).positions == []
    assert real.calls == []


# ------------------------------- Public site ---------------------------------- #


async def test_on_the_public_site_a_follow_fills_at_the_last_sessions_official_close_while_no_session_trades(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = await market(tmp_path, configure=public_site)

    async def no_realtime_quotes(stocks: list[Stock]) -> dict:
        raise RuntimeError("open data has no realtime quote")

    monkeypatch.setattr(stack.quotes, "fetch_realtime_bars", no_realtime_quotes)
    _, in_session = await stack.pipeline.load_ranking_follow()
    stack.clock.current = datetime(2026, 10, 17, 10, 0, tzinfo=TAIWAN_TIMEZONE)

    status = await stack.pipeline.follow_ranking()

    assert in_session == FollowRefusal.OUTSIDE_FOLLOW_WINDOW
    assert [(order.stock_id, order.status, order.limit_price) for order in status.orders] == [
        ("2330", OrderStatus.FILLED, 100),
        ("2317", OrderStatus.FILLED, 50),
    ]


# --------------------------------- Web API ------------------------------------ #


def site(**options) -> CliHarness:
    """The harness's site with the history, the revenue and the quotes above, a member beside the administrator."""
    config = harness_config()
    features = config.features.model_copy(update=options.pop("features", {}))
    ranking = config.ranking.model_copy(update=RANKING_WINDOWS)
    harness = build_harness(config=config.model_copy(update={"ranking": ranking, "features": features}), **options)
    harness.users.add(MEMBER, MEMBER_PASSWORD)

    for stock_id, history in daily_history().items():
        harness.list_stock(stock_id, history, realtime_price=CLOSES[stock_id])

    for stock_id, (august, september) in REVENUES.items():
        harness.archive.monthly_revenues[(stock_id, 2026, 8)] = revenue(stock_id, 2026, 8, august)
        harness.archive.monthly_revenues[(stock_id, 2026, 9)] = revenue(stock_id, 2026, 9, september)

    return harness


async def test_the_web_follow_orders_the_ranking_on_the_mock_account_as_a_run_and_says_what_it_holds() -> None:
    harness = site(sinopac=True)
    harness.hold("1101", 1000, 30.0)

    async with serve(harness) as client:
        offered = (await client.get("/v1/rankings/follow")).json()
        started = await write(client, "POST", "/v1/rankings/follow?broker=shioaji", {})
        follow = await ended(client, started.json()["run_id"])
        orders = (await client.get(f"/v1/runs/{started.json()['run_id']}/orders")).json()

    assert offered == {
        "holdings": {"decided_on": "2026-10-13", "held": [], "lacking": ["2330", "2317"], "left": ["1101"]},
        "refusal": None,
        "running": False,
        "performance": None,
    }
    assert (started.status_code, follow["state"]) == (202, "finished")
    assert (follow["summary"]["workflow"], follow["summary"]["execution_provider"]) == ("ranking_follow", "mock")
    assert [(order.stock_id, order.action) for order in harness.broker.placed] == [
        ("1101", TradeAction.SELL),
        ("2330", TradeAction.BUY),
        ("2317", TradeAction.BUY),
    ]
    assert [(order["stock_id"], order["status"]) for order in orders] == [("1101", "filled"), ("2330", "filled"), ("2317", "filled")]
    assert harness.real_broker.placed == []


async def test_the_web_follow_is_refused_when_nothing_is_left_outside_its_window_and_without_a_quote_login() -> None:
    held = site()
    held.hold("2330", 1, 100.0)
    held.hold("2317", 1, 50.0)

    async with serve(held) as client:
        nothing = await write(client, "POST", "/v1/rankings/follow", {})

    async with serve(site(now=MARKET_CLOSED)) as client:
        closed = await write(client, "POST", "/v1/rankings/follow", {})
        offered = (await client.get("/v1/rankings/follow")).json()

    unquoted = site(realtime_quotes=False)

    async with serve(unquoted) as client:
        no_login = await write(client, "POST", "/v1/rankings/follow", {})

    async with serve(build_harness()) as client:
        no_history = [await client.get("/v1/rankings/follow"), await write(client, "POST", "/v1/rankings/follow", {})]

    assert (nothing.status_code, nothing.json()["code"]) == (409, "nothing_to_follow")
    assert (closed.status_code, closed.json()["code"], offered["refusal"]) == (409, "outside_follow_window", "outside_follow_window")
    assert (no_login.status_code, no_login.json()["code"]) == (403, "realtime_quotes_unavailable")
    assert [(answer.status_code, answer.json()["code"]) for answer in no_history] == [(422, "ranking_unavailable")] * 2
    assert held.journal.runs == unquoted.journal.runs == {} and held.broker.placed == unquoted.broker.placed == []


@pytest.mark.parametrize("hidden", ["ranking", "mock_account"])
async def test_the_follow_is_refused_while_the_site_hides_the_ranking_or_the_mock_account_from_the_user(hidden: str) -> None:
    harness = site(
        features={"ranking": FeatureVisibility.EVERYONE, "mock_account": FeatureVisibility.EVERYONE}
        | {hidden: FeatureVisibility.ADMINISTRATORS}
    )

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as member:
        refused = [await member.get("/v1/rankings/follow"), await write(member, "POST", "/v1/rankings/follow", {})]

    async with serve(harness) as administrator:
        shown = await administrator.get("/v1/rankings/follow")

    async with serve(harness, authorized=False) as visitor:
        signed_out = await visitor.get("/v1/rankings/follow")

    assert [(answer.status_code, answer.json()["code"]) for answer in refused] == [(403, "feature_hidden")] * 2
    assert (shown.status_code, signed_out.status_code) == (200, 401)
    assert harness.journal.runs == {} and harness.broker.placed == []


async def test_a_follow_waits_for_the_users_running_run_and_the_answer_says_one_runs() -> None:
    harness = site()
    release, served = asyncio.Event(), harness.prices.fetch_history

    async def held_history(stocks: list[Stock], start: datetime, end: datetime) -> dict[str, list[Ohlcv]]:
        """The Full Cycle waits at its daily history, which no read of the ranking in an empty account asks for."""
        await release.wait()
        return await served(stocks, start, end)

    harness.prices.fetch_history = held_history

    async with serve(harness) as client:
        running = await write(client, "POST", "/v1/runs/full-cycle", {})
        during = (await client.get("/v1/rankings/follow")).json()
        refused = await write(client, "POST", "/v1/rankings/follow", {})
        release.set()
        await ended(client, running.json()["run_id"])
        after = (await client.get("/v1/rankings/follow")).json()

    assert (refused.status_code, refused.json()["code"]) == (409, "run_in_progress")
    assert (during["running"], after["running"]) == (True, False)
    assert harness.broker.placed == []
