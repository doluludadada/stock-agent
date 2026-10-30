import math
from dataclasses import dataclass

from icontract import ensure, invariant, require

from a_domain.types.enums import TradeAction


@dataclass(frozen=True)
class TradeCost:
    """What executing `gross` worth of shares costs. Fee and tax are whole NT dollars, rounded down."""

    action: TradeAction
    gross: float
    fee: int
    tax: int

    @property
    def net(self) -> float:
        """Signed cash change: a BUY pays gross + fee, a SELL receives gross - fee - tax."""
        if self.action == TradeAction.BUY:
            return -(self.gross + self.fee)

        return self.gross - self.fee - self.tax


@invariant(lambda self: self.fee_rate >= 0 and self.tax_rate >= 0 and self.min_fee >= 0)
@dataclass(frozen=True)
class TradingCostRule:
    """Single source of truth for the broker fee (with its minimum) and the securities transaction tax (SELL only)."""

    fee_rate: float
    tax_rate: float
    min_fee: int

    @require(lambda action: action != TradeAction.HOLD, "HOLD has no cost")
    @require(lambda price: math.isfinite(price) and price > 0)
    @require(lambda quantity: quantity > 0)
    def cost_of(self, action: TradeAction, price: float, quantity: int) -> TradeCost:
        gross = price * quantity
        fee = max(self.min_fee, int(gross * self.fee_rate))
        tax = int(gross * self.tax_rate) if action == TradeAction.SELL else 0

        return TradeCost(action=action, gross=gross, fee=fee, tax=tax)

    @require(lambda price: math.isfinite(price) and price > 0)
    @require(lambda lot_size: lot_size > 0)
    @ensure(lambda result, lot_size: result >= 0 and result % lot_size == 0)
    def max_buy_quantity(self, cash: float, price: float, lot_size: int) -> int:
        """Largest lot-aligned quantity whose gross plus fee fits in `cash`."""
        # The fee is rounded down, so up to one dollar more than cash / (price * (1 + fee_rate)) can still fit.
        quantity = int((cash + 1) // (price * (1 + self.fee_rate))) // lot_size * lot_size

        while quantity > 0 and -self.cost_of(TradeAction.BUY, price, quantity).net > cash:
            quantity -= lot_size

        return max(quantity, 0)
