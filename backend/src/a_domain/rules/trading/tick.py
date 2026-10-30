import math
from collections.abc import Mapping
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

from icontract import ensure, require

from a_domain.types.enums import SecurityKind, TradeAction

TICK_SIZES: Mapping[SecurityKind, tuple[tuple[Decimal, Decimal], ...]] = {
    SecurityKind.STOCK: (
        (Decimal(1000), Decimal("5")),
        (Decimal(500), Decimal("1")),
        (Decimal(100), Decimal("0.5")),
        (Decimal(50), Decimal("0.1")),
        (Decimal(10), Decimal("0.05")),
        (Decimal(0), Decimal("0.01")),
    ),
    SecurityKind.ETF: ((Decimal(50), Decimal("0.05")), (Decimal(0), Decimal("0.01"))),
}
"""The exchanges' price ticks as (lowest price of the band, tick), highest band first. TickRule says where they come from."""

FLOAT_NOISE = Decimal("0.01")
"""
A quote within this fraction of a tick from a tick is that tick carried through a binary float: Yahoo serves
float32 prices, so 28.35 arrives as 28.350000381469727. No exchange price lies that close to a tick without being one.
"""


class TickRule:
    """
    The exchange's price grid. An order's limit price must be a tick, or the exchange refuses it.

    TWSE and TPEx use the same ticks (TICK_SIZES):
    - Stocks: below 10 NT$0.01; 10 to below 50 NT$0.05; 50 to below 100 NT$0.1; 100 to below 500 NT$0.5;
      500 to below 1,000 NT$1; 1,000 and above NT$5.
    - ETFs: below 50 NT$0.01; 50 and above NT$0.05.

    Sources, read 2026-10-31: the TWSE trading mechanism page, regular trading, tick sizes
    (https://www.twse.com.tw/zh/products/system/trading.html), and the TPEx trading system overview,
    section 4, tick sizes (https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html).
    """

    @staticmethod
    def tick_size(stock_id: str, price: Decimal) -> Decimal:
        return next(tick for lowest, tick in TICK_SIZES[SecurityKind.of(stock_id)] if price >= lowest)

    @staticmethod
    def is_tick(stock_id: str, price: float) -> bool:
        exact = Decimal(repr(price))

        return exact > 0 and exact % TickRule.tick_size(stock_id, exact) == 0

    @staticmethod
    @require(lambda action: action != TradeAction.HOLD, "HOLD is not an order")
    @require(lambda price: math.isfinite(price) and price > 0)
    @ensure(lambda result, stock_id: TickRule.is_tick(stock_id, result))
    def limit_price(action: TradeAction, stock_id: str, price: float) -> float:
        """
        The limit price for an order decided at `price`: that price as a tick. An off-tick price rounds up for a BUY and
        down for a SELL, so the order still executes at the decided price. A band edge (10, 50, 100, 500, 1,000) is a
        tick of the band above, so rounding up across it stays on the grid.
        """
        exact = Decimal(repr(price))
        tick = TickRule.tick_size(stock_id, exact)
        ticks = exact / tick
        nearest = ticks.to_integral_value(ROUND_HALF_EVEN)

        if abs(ticks - nearest) > FLOAT_NOISE:
            nearest = ticks.to_integral_value(ROUND_CEILING if action == TradeAction.BUY else ROUND_FLOOR)

        return float(nearest * tick)
