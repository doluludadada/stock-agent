import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

from icontract import ensure, require

from a_domain.types.enums import SecurityKind, TradeAction


@dataclass(frozen=True)
class TickSizeRule:
    """
    The exchange's price grid: an order's limit price must be a multiple of the tick of its price band, or the
    exchange refuses it. TWSE and TPEx use the same ticks. Each band is (lowest price of the band, tick), highest band
    first; market.stock_ticks and market.etf_ticks in config/appsetting.yaml hold them and name their sources.
    """

    stock_ticks: tuple[tuple[Decimal, Decimal], ...]
    etf_ticks: tuple[tuple[Decimal, Decimal], ...]

    def apply(self, stock_id: str, price: Decimal) -> Decimal:
        bands = self.stock_ticks if SecurityKind.of(stock_id) == SecurityKind.STOCK else self.etf_ticks

        return next(tick for lowest, tick in bands if price >= lowest)


@dataclass(frozen=True)
class LimitPriceRule:
    """
    The limit price for an order decided at `price`: that price as a tick. An off-tick price rounds up for a BUY and
    down for a SELL, so the order still executes at the decided price. A band edge (10, 50, 100, 500, 1,000) is a tick
    of the band above, so rounding up across it stays on the grid.

    A quote within `float_tolerance` of a tick, as a fraction of the tick, is that tick carried through a binary float:
    Yahoo serves float32 prices, so 28.35 arrives as 28.350000381469727. No exchange price lies that close to a tick
    without being one.
    """

    tick_size_rule: TickSizeRule
    float_tolerance: Decimal

    @require(lambda action: action != TradeAction.HOLD, "HOLD is not an order")
    @require(lambda price: math.isfinite(price) and price > 0)
    @ensure(lambda self, stock_id, result: Decimal(repr(result)) % self.tick_size_rule.apply(stock_id, Decimal(repr(result))) == 0)
    def apply(self, action: TradeAction, stock_id: str, price: float) -> float:
        exact = Decimal(repr(price))
        tick = self.tick_size_rule.apply(stock_id, exact)
        ticks = exact / tick
        nearest = ticks.to_integral_value(ROUND_HALF_EVEN)

        if abs(ticks - nearest) > self.float_tolerance:
            nearest = ticks.to_integral_value(ROUND_CEILING if action == TradeAction.BUY else ROUND_FLOOR)

        return float(nearest * tick)
