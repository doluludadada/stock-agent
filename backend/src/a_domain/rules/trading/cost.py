import math
from dataclasses import dataclass

from icontract import ensure, invariant, require

from a_domain.model.trading.trade_cost import TradeCost
from a_domain.types.enums import SecurityKind, TradeAction


@invariant(lambda self: self.fee_rate >= 0 and self.tax_rate >= 0 and self.etf_tax_rate >= 0 and self.min_fee >= 0)
@dataclass(frozen=True)
class TradingCostRule:
    """
    Single source of truth for the broker fee (with its minimum) and the securities transaction tax.
    The tax is charged on a SELL only: `tax_rate` for a stock, `etf_tax_rate` for an ETF (SecurityKind).
    """

    fee_rate: float
    tax_rate: float
    etf_tax_rate: float
    min_fee: int

    @require(lambda action: action != TradeAction.HOLD, "HOLD has no cost")
    @require(lambda price: math.isfinite(price) and price > 0)
    @require(lambda quantity: quantity > 0)
    def apply(self, action: TradeAction, stock_id: str, price: float, quantity: int) -> TradeCost:
        gross = price * quantity
        fee = max(self.min_fee, int(gross * self.fee_rate))
        tax_rate = self.etf_tax_rate if SecurityKind.of(stock_id) == SecurityKind.ETF else self.tax_rate
        tax = int(gross * tax_rate) if action == TradeAction.SELL else 0

        return TradeCost(action=action, gross=gross, fee=fee, tax=tax)


@dataclass(frozen=True)
class AffordableQuantityRule:
    """The largest lot-aligned BUY quantity whose gross plus fee fits in the cash."""

    cost_rule: TradingCostRule

    @require(lambda price: math.isfinite(price) and price > 0)
    @require(lambda lot_size: lot_size > 0)
    @ensure(lambda result, lot_size: result >= 0 and result % lot_size == 0)
    def apply(self, cash: float, stock_id: str, price: float, lot_size: int) -> int:
        # The fee is rounded down, so up to one dollar more than cash / (price * (1 + fee_rate)) can still fit.
        quantity = int((cash + 1) // (price * (1 + self.cost_rule.fee_rate))) // lot_size * lot_size

        while quantity > 0 and -self.cost_rule.apply(TradeAction.BUY, stock_id, price, quantity).net > cash:
            quantity -= lot_size

        return max(quantity, 0)
