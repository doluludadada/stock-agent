from datetime import datetime

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.decision import DecisionRule
from a_domain.rules.trading.entry import EntryRule
from a_domain.rules.trading.exit import ExitRule
from a_domain.rules.trading.sizing import SizingRule
from a_domain.types.enums import TradeAction
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

QUOTED_AT = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)
COSTS = TradingCostRule(fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20)


def rule(risk_per_trade_pct: float) -> DecisionRule:
    sizing_rule = SizingRule(risk_per_trade_pct=risk_per_trade_pct, stop_loss_pct=0.10, cost_rule=COSTS)
    return DecisionRule(
        entry_rule=EntryRule(buy_threshold=70, sizing_rule=sizing_rule), exit_rule=ExitRule(stop_loss_pct=0.10, sell_threshold=30)
    )


def scored(stock_id: str, composite_score: int, price: float = 100) -> Stock:
    return Stock(
        stock_id=stock_id,
        realtime_bar=Ohlcv(ts=QUOTED_AT, open=price, high=price, low=price, close=price, volume=1000),
        composite_score=composite_score,
    )


def test_when_cash_runs_out_the_higher_score_wins_and_a_tie_goes_to_the_lower_stock_id() -> None:
    # At 10% risk and a 10% stop a BUY wants all the cash: 998 x 100 + fee 142 = 99,942 of 100,000 leaves 58.
    signals = rule(risk_per_trade_pct=0.10).decide_run(
        [scored("2603", 85), scored("2330", 95), scored("1101", 95)], Account(cash=100_000), now=QUOTED_AT
    )

    assert [(signal.stock_id, signal.action, signal.quantity) for signal in signals] == [
        ("1101", TradeAction.BUY, 998),
        ("2330", TradeAction.HOLD, 0),
        ("2603", TradeAction.HOLD, 0),
    ]


def test_a_runs_buys_never_commit_more_than_the_cash_whatever_the_order_they_arrive_in() -> None:
    stocks = [scored(f"{1101 + index}", 80 + index, price=28.37 + index) for index in range(8)]

    signals = rule(risk_per_trade_pct=0.05).decide_run(stocks, Account(cash=1_000_000), now=QUOTED_AT)

    # The most a BUY can cost is its quantity at the order's limit, the next 0.05 tick up, plus the fee.
    committed = sum(
        -COSTS.cost_of(TradeAction.BUY, signal.stock_id, round(signal.price_at_signal + 0.03, 2), signal.quantity).net
        for signal in signals
        if signal.action == TradeAction.BUY
    )
    assert [signal.stock_id for signal in signals] == [f"{1101 + index}" for index in reversed(range(8))]
    assert sum(signal.action == TradeAction.BUY for signal in signals) == 8
    assert committed <= 1_000_000
