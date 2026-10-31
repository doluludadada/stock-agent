from datetime import UTC, datetime

import pytest

from a_domain.model.trading.order import Order
from a_domain.rules.trading.tick import TickRule
from a_domain.types.enums import OrderType, TimeInForce, TradeAction
from a_domain.types.ids import new_decision_id, new_run_id

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)

BUY, SELL = TradeAction.BUY, TradeAction.SELL


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
        ("006208", 120.07, 120.1, 120.05),
    ],
)
def test_an_off_tick_price_rounds_up_for_a_buy_and_down_for_a_sell_on_its_band(
    stock_id: str, price: float, buy_limit: float, sell_limit: float
) -> None:
    assert (TickRule.limit_price(BUY, stock_id, price), TickRule.limit_price(SELL, stock_id, price)) == (buy_limit, sell_limit)


@pytest.mark.parametrize(
    ("stock_id", "price"),
    [("2330", 9.99), ("2330", 28.35), ("2330", 99.9), ("2330", 100.5), ("2330", 595.0), ("2330", 1085.0), ("0050", 28.37)],
)
def test_a_price_on_the_tick_grid_is_the_limit_for_both_sides(stock_id: str, price: float) -> None:
    assert TickRule.limit_price(BUY, stock_id, price) == TickRule.limit_price(SELL, stock_id, price) == price


@pytest.mark.parametrize(
    ("quote", "tick"),
    [(28.350000381469727, "28.35"), (28.399999618530273, "28.4"), (99.9000015258789, "99.9"), (9.989999771118164, "9.99")],
)
def test_a_float32_quote_is_the_tick_it_stands_for_on_both_sides(quote: float, tick: str) -> None:
    assert repr(TickRule.limit_price(BUY, "2330", quote)) == repr(TickRule.limit_price(SELL, "2330", quote)) == tick


def limit_order(stock_id: str, limit_price: float) -> Order:
    return Order(
        run_id=new_run_id(),
        decision_id=new_decision_id(),
        stock_id=stock_id,
        action=BUY,
        order_type=OrderType.LIMIT,
        quantity=1000,
        limit_price=limit_price,
        time_in_force=TimeInForce.IOC,
        created_at=NOW,
        updated_at=NOW,
    )


def test_an_order_cannot_carry_a_limit_price_off_the_tick_grid() -> None:
    with pytest.raises(ValueError, match="not an exchange tick"):
        limit_order("2330", 28.37)

    with pytest.raises(ValueError, match="not an exchange tick"):
        limit_order("2330", 28.350000381469727)

    assert limit_order("0050", 28.37).limit_price == 28.37
