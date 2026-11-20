from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from typing import Annotated, Literal

from pydantic import Field, validate_call
from pydantic.dataclasses import dataclass

from a_domain.types.enums import SecurityKind, TradeAction
from a_domain.types.values import PositiveFiniteFloat


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
    The limit price of an order decided at `price`, a marketable limit: the exchange fills it at the market's price, so
    the limit bounds what the order pays and does not set it. A BUY's limit is the highest tick at most `offset` above
    the decided price, a SELL's the lowest tick at most `offset` below it (trading.limit_offset_pct), so no fill is
    worse than that. Neither is ever on the far side of the decided price as a tick: an off-tick price rounds up for a
    BUY and down for a SELL, at most one tick, so the order still executes at it, also when `offset` is smaller than a
    tick. A band edge (10, 50, 100, 500, 1,000) is a tick of the band above, so rounding up across it stays on the grid.

    A quote within `float_tolerance` of a tick, as a fraction of the tick, is that tick carried through a binary float:
    a float32 price source serves 28.35 as 28.350000381469727. No exchange price lies that close to a tick
    without being one.
    """

    tick_size_rule: TickSizeRule
    float_tolerance: Decimal
    offset: Annotated[Decimal, Field(ge=0, lt=1)]

    @validate_call
    def apply(self, action: Literal[TradeAction.BUY, TradeAction.SELL], stock_id: str, price: PositiveFiniteFloat) -> float:
        decided = quoted(self, stock_id, price)

        if action == TradeAction.BUY:
            at_most = on_the_grid(self, stock_id, decided * (1 + self.offset), ROUND_FLOOR)
            return float(max(on_the_grid(self, stock_id, decided, ROUND_CEILING), at_most))

        at_least = on_the_grid(self, stock_id, decided * (1 - self.offset), ROUND_CEILING)
        return float(min(on_the_grid(self, stock_id, decided, ROUND_FLOOR), at_least))


def quoted(rule: LimitPriceRule, stock_id: str, price: float) -> Decimal:
    """`price` as the exchange quoted it: the tick it lies within rule.float_tolerance of, else the price itself."""
    exact = Decimal(repr(price))
    tick = rule.tick_size_rule.apply(stock_id, exact)
    nearest = (exact / tick).to_integral_value(ROUND_HALF_EVEN) * tick

    return nearest if abs(exact - nearest) <= rule.float_tolerance * tick else exact


def on_the_grid(rule: LimitPriceRule, stock_id: str, price: Decimal, rounding: str) -> Decimal:
    """The tick `rounding` (ROUND_CEILING or ROUND_FLOOR) takes `price` to, on the grid of the band `price` lies in."""
    tick = rule.tick_size_rule.apply(stock_id, price)

    return (price / tick).to_integral_value(rounding) * tick


def limit_within_band(
    rule: LimitPriceRule,
    action: Literal[TradeAction.BUY, TradeAction.SELL],
    stock_id: str,
    price: float,
    limit: float,
    limit_down: float,
    limit_up: float,
) -> float:
    """
    `limit`, the limit LimitPriceRule set for an order decided at `price`, inside the day's price band from `limit_down`
    to `limit_up`, which TWSE and TPEx refuse an order priced past: a BUY's at most the limit-up, a SELL's at least the
    limit-down, each edge as the tick inside the band. Never past the cap, since it only moves a limit toward the decided
    price, and never on the far side of the decided price as a tick, so the order still executes at it; a decided price
    past the band, which no session trades at, keeps the limit there.
    """
    decided, exact = quoted(rule, stock_id, price), Decimal(repr(limit))

    if action == TradeAction.BUY:
        up = on_the_grid(rule, stock_id, quoted(rule, stock_id, limit_up), ROUND_FLOOR)
        return float(max(on_the_grid(rule, stock_id, decided, ROUND_CEILING), min(exact, up)))

    down = on_the_grid(rule, stock_id, quoted(rule, stock_id, limit_down), ROUND_CEILING)
    return float(min(on_the_grid(rule, stock_id, decided, ROUND_FLOOR), max(exact, down)))
