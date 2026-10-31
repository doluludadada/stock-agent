from datetime import datetime

from support.trading_rules import COSTS, run_decisions_rule

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account
from a_domain.model.trading.position import Position
from a_domain.rules.trading.decision import DecisionCandidatesRule
from a_domain.types.enums import TradeAction
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

QUOTED_AT = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)


def scored(stock_id: str, composite_score: int, price: float = 100) -> Stock:
    return Stock(
        stock_id=stock_id,
        realtime_bar=Ohlcv(ts=QUOTED_AT, open=price, high=price, low=price, close=price, volume=1000),
        composite_score=composite_score,
    )


def test_when_cash_runs_out_the_higher_score_wins_and_a_tie_goes_to_the_lower_stock_id() -> None:
    # At 10% risk and a 10% stop a BUY wants all the cash: 998 x 100 + fee 142 = 99,942 of 100,000 leaves 58.
    signals = run_decisions_rule(risk_per_trade_pct=0.10).apply(
        [scored("2603", 85), scored("2330", 95), scored("1101", 95)], Account(cash=100_000), equity=100_000, now=QUOTED_AT
    )

    assert [(signal.stock_id, signal.action, signal.quantity) for signal in signals] == [
        ("1101", TradeAction.BUY, 998),
        ("2330", TradeAction.HOLD, 0),
        ("2603", TradeAction.HOLD, 0),
    ]


def test_a_runs_buys_never_commit_more_than_the_cash_whatever_the_order_they_arrive_in() -> None:
    stocks = [scored(f"{1101 + index}", 80 + index, price=28.37 + index) for index in range(8)]

    # 1.25% of the equity over a 10% stop is about 125,000 a BUY, so the eighth one is capped by what the cash still pays for.
    signals = run_decisions_rule(risk_per_trade_pct=0.0125).apply(stocks, Account(cash=1_000_000), equity=1_000_000, now=QUOTED_AT)

    # The most a BUY can cost is its quantity at the order's limit, the next 0.05 tick up, plus the fee.
    committed = sum(
        -COSTS.apply(TradeAction.BUY, signal.stock_id, round(signal.price_at_signal + 0.03, 2), signal.quantity, now=QUOTED_AT).net
        for signal in signals
        if signal.action == TradeAction.BUY
    )
    assert [signal.stock_id for signal in signals] == [f"{1101 + index}" for index in reversed(range(8))]
    assert sum(signal.action == TradeAction.BUY for signal in signals) == 8
    assert committed <= 1_000_000


def test_every_buy_of_a_run_risks_a_share_of_the_same_equity_and_the_cash_left_caps_it() -> None:
    # 2% of 3,000,000 over the 10 NT$ stop is 6000 shares, 600,855 with the fee: the first fits the 1,000,000 cash,
    # the second gets what the 399,145 left pays for, fee included, and the third gets none.
    signals = run_decisions_rule(risk_per_trade_pct=0.02).apply(
        [scored("1101", 95), scored("2330", 90), scored("2603", 85)], Account(cash=1_000_000), equity=3_000_000, now=QUOTED_AT
    )

    assert [(signal.stock_id, signal.action, signal.quantity) for signal in signals] == [
        ("1101", TradeAction.BUY, 6000),
        ("2330", TradeAction.BUY, 3985),
        ("2603", TradeAction.HOLD, 0),
    ]


def test_intraday_decides_on_every_survivor_first_then_each_other_held_stock_once() -> None:
    held_failing, survivor, held_survivor, failing = (Stock(stock_id=stock_id) for stock_id in ("1101", "2603", "2330", "2454"))
    positions = [Position(stock_id=stock_id, quantity=1000, average_cost=95) for stock_id in ("1101", "2330")]

    candidates = DecisionCandidatesRule().apply(
        [held_failing, survivor, held_survivor, failing], [survivor, held_survivor], Account(cash=0, positions=positions)
    )

    assert [stock.stock_id for stock in candidates] == ["2603", "2330", "1101"]
