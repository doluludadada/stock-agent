from decimal import Decimal

import pytest
from support.settings import shipped_config

from a_domain.rules.trading.tick import limit_within_band
from a_domain.types.enums import TradeAction

BUY, SELL = TradeAction.BUY, TradeAction.SELL
SHIPPED = shipped_config()
LIMIT_PRICE = SHIPPED.limit_price_rule()
"""The shipped limits: at most trading.limit_offset_pct, 2%, past the decided price."""
TICKS = SHIPPED.market.limit_price_rule(offset=0.0)
"""No offset: the decided price as a tick, the price the mock account's market trades at."""


def test_the_shipped_limits_lie_at_most_two_percent_past_the_decided_price() -> None:
    assert SHIPPED.trading.limit_offset_pct == 0.02


@pytest.mark.parametrize(
    ("stock_id", "price", "buy_limit", "sell_limit"),
    [
        ("2330", 100.0, 102.0, 98.0),
        ("2330", 9.81, 10.0, 9.62),
        ("2330", 9.99, 10.15, 9.8),
        ("2330", 10.05, 10.25, 9.85),
        ("2330", 10.2, 10.4, 10.0),
        ("2330", 49.1, 50.0, 48.15),
        ("2330", 50.0, 51.0, 49.0),
        ("2330", 98.5, 100.0, 96.6),
        ("2330", 102.0, 104.0, 100.0),
        ("2330", 495.0, 504.0, 485.5),
        ("2330", 985.0, 1000.0, 966.0),
        ("2330", 1020.0, 1040.0, 1000.0),
        ("0050", 49.5, 50.45, 48.51),
        ("0050", 50.05, 51.05, 49.05),
    ],
)
def test_a_buy_is_limited_at_the_highest_tick_two_percent_above_and_a_sell_at_the_lowest_two_percent_below(
    stock_id: str, price: float, buy_limit: float, sell_limit: float
) -> None:
    """
    Each cap is rounded toward the decided price on the grid of the band it falls in: a BUY's 2% above 9.81 is 10.0062,
    in the band of 0.05 ticks, so 10.0; a SELL's 2% below 10.2 is 9.996, rounded up to 10.0, a band edge and a tick of
    the band above.
    """
    assert (LIMIT_PRICE.apply(BUY, stock_id, price), LIMIT_PRICE.apply(SELL, stock_id, price)) == (buy_limit, sell_limit)


@pytest.mark.parametrize("stock_id", ["2330", "0050"])
def test_no_limit_crosses_the_cap_or_the_decided_price_and_every_limit_is_on_the_exchange_grid(stock_id: str) -> None:
    exchange_ticks = [(Decimal(1000), "5"), (Decimal(500), "1"), (Decimal(100), "0.5"), (Decimal(50), "0.1"), (Decimal(10), "0.05")]
    if stock_id == "0050":
        exchange_ticks = [(Decimal(50), "0.05")]

    def tick_of(price: Decimal) -> Decimal:
        return next((Decimal(tick) for lowest, tick in exchange_ticks if price >= lowest), Decimal("0.01"))

    def stands_for(price: Decimal) -> Decimal:
        """The tick a price within 1% of a tick stands for (market.tick_float_tolerance), else the price: 700.01 is 700."""
        nearest = round(price / tick_of(price)) * tick_of(price)
        return nearest if abs(price - nearest) <= tick_of(price) / 100 else price

    for cents in range(1, 120_000, 7):
        price = Decimal(cents) / 100
        buy, sell = (Decimal(repr(LIMIT_PRICE.apply(action, stock_id, float(price)))) for action in (BUY, SELL))
        decided_buy, decided_sell = (Decimal(repr(TICKS.apply(action, stock_id, float(price)))) for action in (BUY, SELL))
        cap = stands_for(price)

        assert buy % tick_of(buy) == 0 and sell % tick_of(sell) == 0, f"{stock_id} at {price}: {buy} or {sell} is off the grid"
        assert decided_buy <= buy <= max(decided_buy, cap * Decimal("1.02")), f"BUY {stock_id} at {price} gave {buy}"
        assert min(decided_sell, cap * Decimal("0.98")) <= sell <= decided_sell, f"SELL {stock_id} at {price} gave {sell}"


def test_an_offset_smaller_than_a_tick_leaves_the_order_at_the_decided_price() -> None:
    narrow = SHIPPED.market.limit_price_rule(offset=0.001)

    assert (narrow.apply(BUY, "2330", 100.0), narrow.apply(SELL, "2330", 100.0)) == (100.0, 99.9)
    assert (narrow.apply(BUY, "2330", 100.2), narrow.apply(SELL, "2330", 100.2)) == (100.5, 100.0)


@pytest.mark.parametrize(
    ("quote", "buy_limit", "sell_limit"), [(28.350000381469727, "28.9", "27.8"), (49.999996185302734, "51.0", "49.0")]
)
def test_a_float32_quote_is_capped_from_the_tick_it_stands_for(quote: float, buy_limit: str, sell_limit: str) -> None:
    assert (repr(LIMIT_PRICE.apply(BUY, "2330", quote)), repr(LIMIT_PRICE.apply(SELL, "2330", quote))) == (buy_limit, sell_limit)


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
def test_with_no_offset_an_off_tick_price_rounds_up_for_a_buy_and_down_for_a_sell_on_its_band(
    stock_id: str, price: float, buy_limit: float, sell_limit: float
) -> None:
    assert (TICKS.apply(BUY, stock_id, price), TICKS.apply(SELL, stock_id, price)) == (buy_limit, sell_limit)


@pytest.mark.parametrize(
    ("stock_id", "price"),
    [("2330", 9.99), ("2330", 28.35), ("2330", 99.9), ("2330", 100.5), ("2330", 595.0), ("2330", 1085.0), ("0050", 28.37)],
)
def test_with_no_offset_a_price_on_the_tick_grid_is_the_limit_for_both_sides(stock_id: str, price: float) -> None:
    assert TICKS.apply(BUY, stock_id, price) == TICKS.apply(SELL, stock_id, price) == price


@pytest.mark.parametrize(
    ("quote", "tick"),
    [(28.350000381469727, "28.35"), (28.399999618530273, "28.4"), (99.9000015258789, "99.9"), (9.989999771118164, "9.99")],
)
def test_with_no_offset_a_float32_quote_is_the_tick_it_stands_for_on_both_sides(quote: float, tick: str) -> None:
    assert repr(TICKS.apply(BUY, "2330", quote)) == repr(TICKS.apply(SELL, "2330", quote)) == tick


@pytest.mark.parametrize(
    ("action", "price", "band", "limit"),
    [
        (SELL, 87.0, (85.5, 104.5), 85.5),
        (BUY, 103.0, (85.5, 104.5), 104.5),
        (SELL, 85.5, (85.5, 104.5), 85.5),
        (BUY, 104.5, (85.5, 104.5), 104.5),
        (BUY, 10.3, (8.55, 10.45), 10.45),
        (SELL, 8.7, (8.55, 10.45), 8.55),
        (BUY, 100.0, (90.0, 110.0), 102.0),
        (SELL, 100.0, (90.0, 110.0), 98.0),
    ],
    ids=[
        "stop-loss-sell-past-the-limit-down",
        "buy-past-the-limit-up",
        "sell-decided-at-the-limit-down",
        "buy-decided-at-the-limit-up",
        "buy-cap-across-a-tick-band-edge",
        "sell-cap-under-a-low-limit-down",
        "buy-inside-the-band",
        "sell-inside-the-band",
    ],
)
def test_a_limit_past_the_days_price_band_lies_at_the_bands_edge_and_one_inside_it_is_left_as_it_is(
    action: TradeAction, price: float, band: tuple[float, float], limit: float
) -> None:
    """
    TWSE and TPEx refuse an order priced past the day's band, 10% each side of the reference price: a reference of 95
    bands the day from 85.5 to 104.5, where the 2% cap puts a SELL decided at 87 at 85.3 and a BUY decided at 103 at
    105.0; a reference of 9.5 bands it from 8.55 to 10.45, where the cap puts a BUY decided at 10.3 at 10.5.
    """
    capped = LIMIT_PRICE.apply(action, "2330", price)

    assert limit_within_band(LIMIT_PRICE, action, "2330", price, capped, *band) == limit


@pytest.mark.parametrize(("action", "price", "limit"), [(BUY, 105.0, 105.0), (SELL, 85.0, 85.0)])
def test_a_limit_is_never_moved_to_the_far_side_of_a_decided_price_that_lies_past_the_band(
    action: TradeAction, price: float, limit: float
) -> None:
    """No session trades past its band, so such a price is a stale one; the order stays one that executes at it."""
    capped = LIMIT_PRICE.apply(action, "2330", price)

    assert limit_within_band(LIMIT_PRICE, action, "2330", price, capped, 85.5, 104.5) == limit
