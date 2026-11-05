from datetime import date, datetime

import pytest

from a_domain.rules.trading.cost import AffordableQuantityRule, TradingCostRule
from a_domain.types.enums import TradeAction
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE
from d_presentation.dependencies import get_project_root, load_settings

RULE = TradingCostRule(fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20, bond_etf_tax_exempt_until=date(2026, 12, 31))
NOW = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)
LAST_EXEMPT_SESSION = datetime(2026, 12, 31, 13, 0, tzinfo=TAIWAN_TIMEZONE)
FIRST_TAXED_SESSION = datetime(2027, 1, 4, 9, 30, tzinfo=TAIWAN_TIMEZONE)


def test_buy_pays_gross_plus_fee_rounded_down_and_no_tax() -> None:
    cost = RULE.apply(TradeAction.BUY, "2330", price=100, quantity=1000, now=NOW)

    assert (cost.gross, cost.fee, cost.tax, cost.net) == (100_000, 142, 0, -100_142)


def test_small_trade_pays_the_minimum_fee() -> None:
    cost = RULE.apply(TradeAction.BUY, "2330", price=100, quantity=10, now=NOW)

    assert (cost.fee, cost.net) == (20, -1020)


def test_sell_receives_gross_minus_fee_and_transaction_tax() -> None:
    cost = RULE.apply(TradeAction.SELL, "2330", price=100, quantity=1000, now=NOW)

    assert (cost.fee, cost.tax, cost.net) == (142, 300, 99_558)


@pytest.mark.parametrize(
    ("cash", "price", "lot_size", "expected"),
    [(1020, 100, 1, 10), (1019, 100, 1, 9), (100_142, 100, 1000, 1000), (100_141, 100, 1000, 0), (0, 100, 1, 0)],
)
def test_the_affordable_quantity_leaves_room_for_the_fee(cash: float, price: float, lot_size: int, expected: int) -> None:
    assert (
        AffordableQuantityRule(cost_rule=RULE).apply(cash=cash, stock_id="2330", price=price, lot_size=lot_size, now=NOW) == expected
    )


@pytest.mark.parametrize(
    ("stock_id", "now", "tax"),
    [
        ("2330", LAST_EXEMPT_SESSION, 300),
        ("2330", FIRST_TAXED_SESSION, 300),
        ("0050", LAST_EXEMPT_SESSION, 100),
        ("00878", FIRST_TAXED_SESSION, 100),
        ("006208", NOW, 100),
        ("00679B", NOW, 0),
        ("00679B", LAST_EXEMPT_SESSION, 0),
        ("00679B", FIRST_TAXED_SESSION, 100),
    ],
)
def test_a_sell_pays_the_stock_rate_on_a_stock_the_etf_rate_on_an_etf_and_nothing_on_a_bond_etf_until_its_exemption_ends(
    stock_id: str, now: datetime, tax: int
) -> None:
    assert RULE.apply(TradeAction.SELL, stock_id, price=100, quantity=1000, now=now).tax == tax


def test_a_bond_etf_buy_pays_no_tax_on_either_side_of_the_exemption() -> None:
    for now in (LAST_EXEMPT_SESSION, FIRST_TAXED_SESSION):
        assert RULE.apply(TradeAction.BUY, "00679B", price=100, quantity=1000, now=now).tax == 0


def test_the_shipped_config_taxes_etf_sells_at_a_third_of_the_stock_rate_and_bond_etf_sells_from_2027() -> None:
    cost_rule = load_settings(get_project_root()).market.cost_rule()

    assert cost_rule.apply(TradeAction.SELL, "2330", price=50, quantity=2000, now=NOW).tax == 300
    assert cost_rule.apply(TradeAction.SELL, "0056", price=50, quantity=2000, now=NOW).tax == 100
    assert cost_rule.apply(TradeAction.SELL, "00679B", price=50, quantity=2000, now=LAST_EXEMPT_SESSION).tax == 0
    assert cost_rule.apply(TradeAction.SELL, "00679B", price=50, quantity=2000, now=FIRST_TAXED_SESSION).tax == 100
