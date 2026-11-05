from decimal import Decimal

import pytest

from a_domain.types.enums import TradeAction
from d_presentation.dependencies import get_project_root, load_settings

BUY, SELL = TradeAction.BUY, TradeAction.SELL
LIMIT_PRICE = load_settings(get_project_root()).market.limit_price_rule()


@pytest.mark.parametrize(
    ("stock_id", "price", "buy_limit", "sell_limit"),
    [
        ("2330", 9.996, 10.0, 9.99),
        ("2330", 28.37, 28.4, 28.35),
        ("2330", 49.99, 50.0, 49.95),
        ("2330", 99.93, 100.0, 99.9),
        ("2330", 100.2, 100.5, 100.0),
        ("2330", 499.7, 500.0, 499.5),
        ("2330", 501.5, 502.0, 501.0),
        ("2330", 1003.0, 1005.0, 1000.0),
        ("0050", 28.373, 28.38, 28.37),
        ("00878", 50.02, 50.05, 50.0),
        ("00679B", 50.02, 50.05, 50.0),
        ("006208", 120.07, 120.1, 120.05),
    ],
)
def test_an_off_tick_price_rounds_up_for_a_buy_and_down_for_a_sell_on_its_band(
    stock_id: str, price: float, buy_limit: float, sell_limit: float
) -> None:
    assert (LIMIT_PRICE.apply(BUY, stock_id, price), LIMIT_PRICE.apply(SELL, stock_id, price)) == (buy_limit, sell_limit)


@pytest.mark.parametrize(
    ("stock_id", "price"),
    [("2330", 9.99), ("2330", 28.35), ("2330", 99.9), ("2330", 100.5), ("2330", 595.0), ("2330", 1085.0), ("0050", 28.37)],
)
def test_a_price_on_the_tick_grid_is_the_limit_for_both_sides(stock_id: str, price: float) -> None:
    assert LIMIT_PRICE.apply(BUY, stock_id, price) == LIMIT_PRICE.apply(SELL, stock_id, price) == price


@pytest.mark.parametrize(
    ("quote", "tick"),
    [(28.350000381469727, "28.35"), (28.399999618530273, "28.4"), (99.9000015258789, "99.9"), (9.989999771118164, "9.99")],
)
def test_a_float32_quote_is_the_tick_it_stands_for_on_both_sides(quote: float, tick: str) -> None:
    assert repr(LIMIT_PRICE.apply(BUY, "2330", quote)) == repr(LIMIT_PRICE.apply(SELL, "2330", quote)) == tick


@pytest.mark.parametrize("stock_id", ["2330", "0050"])
def test_no_price_gives_a_limit_off_the_exchange_grid(stock_id: str) -> None:
    exchange_ticks = [(Decimal(1000), "5"), (Decimal(500), "1"), (Decimal(100), "0.5"), (Decimal(50), "0.1"), (Decimal(10), "0.05")]
    if stock_id == "0050":
        exchange_ticks = [(Decimal(50), "0.05")]

    for cents in range(1, 120_000, 7):
        for action in (BUY, SELL):
            limit = Decimal(repr(LIMIT_PRICE.apply(action, stock_id, cents / 100)))
            tick = next((Decimal(tick) for lowest, tick in exchange_ticks if limit >= lowest), Decimal("0.01"))

            assert limit % tick == 0, f"{action} {stock_id} at {cents / 100} gave {limit}, off the {tick} grid"
