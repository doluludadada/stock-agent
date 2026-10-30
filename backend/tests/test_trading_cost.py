import pytest

from a_domain.rules.trading.cost import TradingCostRule
from a_domain.types.enums import TradeAction

RULE = TradingCostRule(fee_rate=0.001425, tax_rate=0.003, min_fee=20)


def test_buy_pays_gross_plus_fee_rounded_down_and_no_tax() -> None:
    cost = RULE.cost_of(TradeAction.BUY, price=100, quantity=1000)

    assert (cost.gross, cost.fee, cost.tax, cost.net) == (100_000, 142, 0, -100_142)


def test_small_trade_pays_the_minimum_fee() -> None:
    cost = RULE.cost_of(TradeAction.BUY, price=100, quantity=10)

    assert (cost.fee, cost.net) == (20, -1020)


def test_sell_receives_gross_minus_fee_and_transaction_tax() -> None:
    cost = RULE.cost_of(TradeAction.SELL, price=100, quantity=1000)

    assert (cost.fee, cost.tax, cost.net) == (142, 300, 99_558)


@pytest.mark.parametrize(
    ("cash", "price", "lot_size", "expected"),
    [(1020, 100, 1, 10), (1019, 100, 1, 9), (100_142, 100, 1000, 1000), (100_141, 100, 1000, 0), (0, 100, 1, 0)],
)
def test_max_buy_quantity_leaves_room_for_the_fee(cash: float, price: float, lot_size: int, expected: int) -> None:
    assert RULE.max_buy_quantity(cash=cash, price=price, lot_size=lot_size) == expected
