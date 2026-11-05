from datetime import datetime, timedelta

import pytest
from support.trading_rules import COSTS, sizing_rule

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account, Position
from a_domain.rules.trading.account_value import AccountValueRule, PositionValueRule
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

QUOTED_AT = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)


def bar(close: float, at: datetime = QUOTED_AT) -> Ohlcv:
    return Ohlcv(ts=at, open=close, high=close, low=close, close=close, volume=1000)


@pytest.mark.parametrize(
    ("equity", "cash", "risk_per_trade_pct", "stop_loss_pct", "lot_size", "expected"),
    [
        (1_000_000, 1_000_000, 0.02, 0.10, 1, 2000),
        (2_000_000, 1_000_000, 0.02, 0.10, 1, 4000),
        (2_000_000, 100_142, 0.02, 0.10, 1, 1000),
        (1_000_000, 100_142, 1.0, 0.01, 1, 1000),
        (1_000_000, 100_141, 1.0, 0.01, 1, 999),
        (1_000_000, 100_142, 1.0, 0.01, 1000, 1000),
        (100_000, 0, 0.02, 0.10, 1, 0),
    ],
)
def test_quantity_is_the_equity_risk_budget_capped_by_cash_after_fees(
    equity: float, cash: float, risk_per_trade_pct: float, stop_loss_pct: float, lot_size: int, expected: int
) -> None:
    rule = sizing_rule(risk_per_trade_pct, stop_loss_pct, lot_size)

    assert rule.apply(account=Account(cash=cash), equity=equity, stock_id="2330", price=100, now=QUOTED_AT) == expected


def test_a_buy_from_an_off_tick_quote_is_sized_at_its_order_limit_so_the_cash_covers_the_order() -> None:
    rule = sizing_rule(risk_per_trade_pct=1.0, stop_loss_pct=0.01)

    # 1000 x 28.37 + fee 40 is exactly the cash, but the order's limit is the next tick, 28.40: 998 x 28.40 + 40 fits, 999 does not.
    assert rule.apply(account=Account(cash=28_410), equity=28_410, stock_id="2330", price=28.37, now=QUOTED_AT) == 998


def test_equity_marks_each_position_at_its_quote_else_its_last_daily_close_else_its_average_cost() -> None:
    positions = [Position(stock_id=stock_id, quantity=1000, average_cost=90.0) for stock_id in ("2330", "2317", "2603")]
    yesterday = QUOTED_AT - timedelta(days=1)
    stocks = [
        Stock(stock_id="2330", ohlcv=[bar(95, yesterday)], realtime_bar=bar(100)),
        Stock(stock_id="2317", ohlcv=[bar(94, yesterday - timedelta(days=1)), bar(95, yesterday)]),
        Stock(stock_id="2603"),
    ]

    value_rule = AccountValueRule(position_value_rule=PositionValueRule(cost_rule=COSTS))
    equity = value_rule.apply(Account(cash=100_000, positions=positions), stocks).equity

    assert equity == 100_000 + 1000 * 100 + 1000 * 95 + 1000 * 90
