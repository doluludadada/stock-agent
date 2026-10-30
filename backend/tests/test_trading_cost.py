import pytest

from a_domain.rules.trading.cost import TradingCostRule
from a_domain.types.enums import TradeAction
from c_infrastructure.system.config_loader import load_settings

RULE = TradingCostRule(fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20)


def test_buy_pays_gross_plus_fee_rounded_down_and_no_tax() -> None:
    cost = RULE.cost_of(TradeAction.BUY, "2330", price=100, quantity=1000)

    assert (cost.gross, cost.fee, cost.tax, cost.net) == (100_000, 142, 0, -100_142)


def test_small_trade_pays_the_minimum_fee() -> None:
    cost = RULE.cost_of(TradeAction.BUY, "2330", price=100, quantity=10)

    assert (cost.fee, cost.net) == (20, -1020)


def test_sell_receives_gross_minus_fee_and_transaction_tax() -> None:
    cost = RULE.cost_of(TradeAction.SELL, "2330", price=100, quantity=1000)

    assert (cost.fee, cost.tax, cost.net) == (142, 300, 99_558)


@pytest.mark.parametrize(
    ("cash", "price", "lot_size", "expected"),
    [(1020, 100, 1, 10), (1019, 100, 1, 9), (100_142, 100, 1000, 1000), (100_141, 100, 1000, 0), (0, 100, 1, 0)],
)
def test_max_buy_quantity_leaves_room_for_the_fee(cash: float, price: float, lot_size: int, expected: int) -> None:
    assert RULE.max_buy_quantity(cash=cash, stock_id="2330", price=price, lot_size=lot_size) == expected


@pytest.mark.parametrize(("stock_id", "tax"), [("2330", 300), ("0050", 100), ("00878", 100), ("006208", 100)])
def test_an_etf_sell_pays_the_etf_tax_rate_and_a_stock_sell_the_stock_rate(stock_id: str, tax: int) -> None:
    assert RULE.cost_of(TradeAction.SELL, stock_id, price=100, quantity=1000).tax == tax


def test_the_shipped_config_taxes_etf_sells_at_a_third_of_the_stock_rate() -> None:
    cost_rule = load_settings().market.cost_rule()

    assert cost_rule.cost_of(TradeAction.SELL, "2330", price=50, quantity=2000).tax == 300
    assert cost_rule.cost_of(TradeAction.SELL, "0056", price=50, quantity=2000).tax == 100
