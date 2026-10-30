import pytest

from a_domain.model.trading.account import Account
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.sizing import SizingRule

COSTS = TradingCostRule(fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20)


@pytest.mark.parametrize(
    ("cash", "risk_per_trade_pct", "stop_loss_pct", "lot_size", "expected"),
    [
        (1_000_000, 0.02, 0.10, 1, 2000),
        (100_142, 1.0, 0.01, 1, 1000),
        (100_141, 1.0, 0.01, 1, 999),
        (100_142, 1.0, 0.01, 1000, 1000),
        (0, 0.02, 0.10, 1, 0),
    ],
)
def test_quantity_is_the_risk_budget_capped_by_cash_after_fees(
    cash: float, risk_per_trade_pct: float, stop_loss_pct: float, lot_size: int, expected: int
) -> None:
    rule = SizingRule(risk_per_trade_pct=risk_per_trade_pct, stop_loss_pct=stop_loss_pct, cost_rule=COSTS, lot_size=lot_size)

    assert rule.calculate(account=Account(cash=cash), stock_id="2330", price=100) == expected


def test_a_buy_from_an_off_tick_quote_is_sized_at_its_order_limit_so_the_cash_covers_the_order() -> None:
    rule = SizingRule(risk_per_trade_pct=1.0, stop_loss_pct=0.01, cost_rule=COSTS)

    # 1000 x 28.37 + fee 40 is exactly the cash, but the order's limit is the next tick, 28.40: 998 x 28.40 + 40 fits, 999 does not.
    assert rule.calculate(account=Account(cash=28_410), stock_id="2330", price=28.37) == 998
