"""
A follow of a finished Full Cycle into the user's mock account, on a real SQLite journal and mock book: on the personal
site at a fresh realtime quote in continuous trading, on the public site at the official close of the last closed
session while no session trades. A decision is followed once a follow order of it filled since the account opened; a
refused or skipped follow leaves it open, and a reset opens every decision again.
"""

from datetime import timedelta

import pytest
from trading_stack import MONDAY_10_00, TradingStack, bar, open_stack

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account, Position
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.follow import FollowRule, FollowWindowRule, OpenDecisionsRule
from a_domain.rules.trading.order_rule import BrokerLink
from a_domain.types.enums import (
    Audience,
    ExecutionProvider,
    FollowRefusal,
    OrderPricing,
    OrderStatus,
    SignalSource,
    TradeAction,
    TradingPhase,
    Workflow,
)
from a_domain.types.ids import RunId

pytestmark = pytest.mark.asyncio

FRIDAY_CLOSE = MONDAY_10_00 - timedelta(days=3, hours=-3, minutes=-30)
SATURDAY_10_00 = FRIDAY_CLOSE + timedelta(hours=20, minutes=30)
MONDAY_14_00 = MONDAY_10_00 + timedelta(hours=4)


def full_cycle(workflow: Workflow = Workflow.FULL_CYCLE, finished: bool = True) -> SystemStats:
    return SystemStats(
        workflow=workflow,
        execution_provider=ExecutionProvider.MOCK,
        start_time=FRIDAY_CLOSE + timedelta(hours=7),
        end_time=FRIDAY_CLOSE + timedelta(hours=7, minutes=20) if finished else None,
    )


def decision(stock_id: str = "2330", action: TradeAction = TradeAction.BUY, quantity: int = 1000) -> TradeSignal:
    """A decision as Full Cycle records it: priced at Friday's daily close."""
    return TradeSignal(
        stock_id=stock_id,
        action=action,
        source=SignalSource.COMBINED,
        score=88,
        reason="strong trend",
        quantity=quantity,
        generated_at=FRIDAY_CLOSE + timedelta(hours=7, minutes=10),
        price_at_signal=98,
        price_observed_at=FRIDAY_CLOSE,
    )


async def recorded(stack: TradingStack, *decisions: TradeSignal, run: SystemStats | None = None) -> RunId:
    run = run or full_cycle()
    await stack.journal.save_run(run)
    await stack.journal.save_signals(run.run_id, list(decisions))
    return run.run_id


async def followed(stack: TradingStack, run_id: RunId):
    return await stack.pipeline.follow_run(run_id)


# ----------------------------------- Rules ------------------------------------ #


def test_only_a_finished_full_cycle_has_decisions_open_to_follow_one_per_stock_and_a_sell_only_of_a_held_stock() -> None:
    buy, sell, hold, second = decision(), decision("2603", TradeAction.SELL), decision("1101", TradeAction.HOLD, 0), decision()
    unheld_sell = decision("2317", TradeAction.SELL)
    account = Account(cash=1_000_000, positions=[Position(stock_id="2603", quantity=1000, average_cost=90)])
    rule = OpenDecisionsRule()

    assert rule.apply(full_cycle(), [buy, sell, hold, second, unheld_sell], [], account) == [buy, sell]
    assert rule.apply(full_cycle(finished=False), [buy], [], account) == []
    assert rule.apply(full_cycle(Workflow.BUZZ_SCAN), [buy], [], account) == []
    assert rule.apply(full_cycle(Workflow.FOLLOW), [buy], [], account) == []


@pytest.mark.parametrize(
    ("pricing", "phase", "refusal"),
    [
        (OrderPricing.REALTIME_QUOTE, TradingPhase.CONTINUOUS, None),
        (OrderPricing.REALTIME_QUOTE, TradingPhase.CLOSED, FollowRefusal.OUTSIDE_FOLLOW_WINDOW),
        (OrderPricing.OFFICIAL_CLOSE, TradingPhase.CLOSED, None),
        (OrderPricing.OFFICIAL_CLOSE, TradingPhase.CONTINUOUS, FollowRefusal.OUTSIDE_FOLLOW_WINDOW),
    ],
)
def test_a_follow_starts_only_in_the_phase_its_site_prices_orders_in(
    pricing: OrderPricing, phase: TradingPhase, refusal: FollowRefusal | None
) -> None:
    assert FollowWindowRule(pricing=pricing).apply([decision()], phase) == refusal
    assert FollowWindowRule(pricing=pricing).apply([], phase) == FollowRefusal.NOTHING_TO_FOLLOW


def test_a_sell_follows_with_at_most_the_shares_held_and_not_at_all_without_them() -> None:
    stock = Stock(stock_id="2330", realtime_bar=bar(MONDAY_10_00, 101))
    held = Position(stock_id="2330", quantity=400, average_cost=90)
    sell = decision(action=TradeAction.SELL)

    follow = FollowRule().apply(sell, stock, held, MONDAY_10_00)
    assert isinstance(follow, TradeSignal)
    assert (follow.quantity, follow.price_at_signal, follow.source, follow.followed_decision_id) == (
        400,
        101,
        SignalSource.FOLLOW,
        sell.decision_id,
    )
    assert FollowRule().apply(sell, stock, None, MONDAY_10_00) == "not held now"


# ------------------------------ Personal site --------------------------------- #


async def test_a_follow_buys_the_runs_decision_at_a_fresh_quote_and_names_the_run_it_came_from(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    run_id = await recorded(stack, decision())

    status = await followed(stack, run_id)

    [order] = status.orders
    [follow] = await stack.journal.signals_of(status.stats.run_id)
    account = await stack.broker.get_account()
    [(trade, source)] = await stack.journal.trades(ExecutionProvider.MOCK, account.opened_at, 10, 0)
    assert (order.status, order.limit_price, order.filled_quantity) == (OrderStatus.FILLED, 100, 1000)
    assert (follow.source, follow.price_at_signal, follow.followed_decision_id) == (
        SignalSource.FOLLOW,
        100,
        status.followable_signals[0].decision_id,
    )
    assert status.stats.followed_run_id == run_id
    assert account.position_for("2330") is not None
    assert (trade.id, source.run_id, source.workflow) == (order.id, run_id, Workflow.FULL_CYCLE)


async def test_a_second_follow_finds_nothing_left_and_orders_nothing(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    run_id = await recorded(stack, decision())
    await followed(stack, run_id)

    again = await followed(stack, run_id)

    assert again.follow_refusal == FollowRefusal.NOTHING_TO_FOLLOW
    assert again.orders == []
    assert (await stack.pipeline.load_follow(run_id)).follow_refusal == FollowRefusal.NOTHING_TO_FOLLOW


async def test_outside_continuous_trading_the_follow_is_refused_before_anything_is_recorded(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    run_id = await recorded(stack, decision())
    stack.clock.current = MONDAY_14_00

    status = await stack.pipeline.load_follow(run_id)

    assert status.follow_refusal == FollowRefusal.OUTSIDE_FOLLOW_WINDOW
    assert [signal.stock_id for signal in status.followable_signals] == ["2330"]


async def test_a_follow_refused_for_a_stale_quote_leaves_the_decision_open(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    run_id = await recorded(stack, decision())
    stack.quotes.realtime["2330"] = bar(MONDAY_10_00 - timedelta(minutes=30), 100)

    status = await followed(stack, run_id)

    [order] = status.orders
    assert order.status == OrderStatus.REJECTED and (order.reason or "").startswith("STALE_PRICE: ")
    assert [signal.stock_id for signal in (await stack.pipeline.load_follow(run_id)).followable_signals] == ["2330"]


async def test_a_sell_of_a_stock_not_held_is_nothing_to_follow_until_the_account_holds_it(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    sell_run = await recorded(stack, decision(action=TradeAction.SELL, quantity=2000))

    before = await stack.pipeline.load_follow(sell_run)
    await followed(stack, await recorded(stack, decision()))
    status = await followed(stack, sell_run)

    [order] = status.orders
    assert (before.follow_refusal, before.followable_signals) == (FollowRefusal.NOTHING_TO_FOLLOW, [])
    assert (order.action, order.quantity, order.status) == (TradeAction.SELL, 1000, OrderStatus.FILLED)


# ------------------------------- Public site ---------------------------------- #


def public(config) -> None:
    config.audience = Audience.PUBLIC


async def test_on_the_public_site_a_follow_fills_at_the_last_sessions_official_close_while_no_session_trades(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = await open_stack(tmp_path, configure=public)

    async def no_realtime_quotes(stocks: list[Stock]) -> dict:
        raise RuntimeError("open data has no realtime quote")

    monkeypatch.setattr(stack.quotes, "fetch_realtime_bars", no_realtime_quotes)
    stack.quotes.daily["2330"] = [bar(FRIDAY_CLOSE, 77)]
    stack.clock.current = SATURDAY_10_00
    run_id = await recorded(stack, decision())

    status = await followed(stack, run_id)

    [order] = status.orders
    assert (order.status, order.limit_price, order.filled_quantity) == (OrderStatus.FILLED, 77, 1000)
    assert not [error for error in status.stats.errors if "realtime" in error]


async def test_on_the_public_site_a_follow_waits_for_the_session_to_close(tmp_path) -> None:
    stack = await open_stack(tmp_path, configure=public)
    run_id = await recorded(stack, decision())

    assert (await stack.pipeline.load_follow(run_id)).follow_refusal == FollowRefusal.OUTSIDE_FOLLOW_WINDOW


async def test_on_the_public_site_an_older_close_is_refused_and_the_decision_stays_open(tmp_path) -> None:
    stack = await open_stack(tmp_path, configure=public)
    stack.quotes.realtime.clear()
    stack.quotes.daily["2330"] = [bar(FRIDAY_CLOSE - timedelta(days=1), 77)]
    stack.clock.current = SATURDAY_10_00
    run_id = await recorded(stack, decision())

    [order] = (await followed(stack, run_id)).orders

    assert order.status == OrderStatus.REJECTED and (order.reason or "").startswith("STALE_PRICE: ")
    assert len((await stack.pipeline.load_follow(run_id)).followable_signals) == 1


# ---------------------------------- Reset ------------------------------------- #


async def test_a_reset_reopens_the_account_with_the_new_capital_and_every_decision(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    run_id = await recorded(stack, decision())
    await followed(stack, run_id)
    stack.clock.current = MONDAY_10_00 + timedelta(minutes=5)

    account = await stack.pipeline.reset_mock_account(500_000)

    assert (account.cash, account.positions, account.profit) == (500_000, [], 0)
    assert account.opening is not None and account.opening.opened_at == stack.clock.current
    assert await stack.journal.trades(ExecutionProvider.MOCK, account.opened_at, 10, 0) == []
    assert len(await stack.journal.orders_of((await stack.journal.recent_runs(1))[0].run_id)) == 1
    assert (await stack.pipeline.load_follow(run_id)).follow_refusal is None


async def test_the_account_history_starts_at_the_opening(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    run_id = await recorded(stack, decision())
    await followed(stack, run_id)
    before = await stack.pipeline.load_account_history(None)
    stack.clock.current = MONDAY_10_00 + timedelta(minutes=5)
    await stack.pipeline.reset_mock_account(2_000_000)

    after = await stack.pipeline.load_account_history(None)

    assert before.equity_curve and before.account.profit is not None
    assert after.equity_curve == {} and (after.account.cash, after.account.profit) == (2_000_000, 0)


async def test_a_run_the_journal_does_not_hold_has_nothing_to_follow(tmp_path) -> None:
    stack = await open_stack(tmp_path)

    status = await stack.pipeline.load_follow(RunId(full_cycle().run_id))

    assert (status.followed_run, status.follow_refusal) == (None, FollowRefusal.NOTHING_TO_FOLLOW)


class RealBroker:
    """A real broker (IExecutionProvider) that records every call and refuses it: no follow may reach it."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def connect(self) -> None:
        self.calls.append("connect")

    def link(self) -> BrokerLink:
        return BrokerLink(broker=ExecutionProvider.SHIOAJI, up=True, simulation=True)

    async def place_order(self, order: Order) -> Order:
        self.calls.append("place_order")
        raise AssertionError("a follow sent an order to the real broker")

    async def get_account(self) -> Account:
        self.calls.append("get_account")
        raise AssertionError("a follow read the real broker's account")

    def refusal_for(self, order: Order, account: Account) -> None:
        self.calls.append("refusal_for")


async def test_a_follow_on_a_pipeline_built_for_sinopac_never_reaches_it_and_orders_nothing(tmp_path) -> None:
    real = RealBroker()
    stack = await open_stack(tmp_path, real_broker=real, broker=ExecutionProvider.SHIOAJI)
    run_id = await recorded(stack, decision())

    candidates = await stack.pipeline.load_follow(run_id)
    status = await followed(stack, run_id)

    [order] = status.orders
    assert (len(candidates.followable_signals), order.status, order.filled_quantity) == (1, OrderStatus.REJECTED, 0)
    assert order.reason is not None and order.reason.startswith("BROKER_NOT_CHOSEN: the run chose shioaji")
    assert (await stack.broker.get_account()).position_for("2330") is None
    assert real.calls == []
