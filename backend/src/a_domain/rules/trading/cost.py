import math
from dataclasses import dataclass
from datetime import date, datetime

from icontract import ensure, invariant, require

from a_domain.model.trading.trade_cost import TradeCost
from a_domain.types.enums import SecurityKind, TradeAction


@invariant(lambda self: self.fee_rate >= 0 and self.tax_rate >= 0 and self.etf_tax_rate >= 0 and self.min_fee >= 0)
@dataclass(frozen=True)
class TradingCostRule:
    """
    Single source of truth for the broker fee (with its minimum) and the securities transaction tax.
    The tax is charged on a SELL only: `tax_rate` for a stock and `etf_tax_rate` for an ETF (SecurityKind). A bond ETF
    traded on or before `bond_etf_tax_exempt_until` pays none, and `etf_tax_rate` after it. The trading date is the date
    of `now`, the trade's time, in its own zone; every Taiwan trading hour falls on the same date in UTC and in Taipei.
    """

    fee_rate: float
    tax_rate: float
    etf_tax_rate: float
    min_fee: int
    bond_etf_tax_exempt_until: date

    @require(lambda action: action != TradeAction.HOLD, "HOLD has no cost")
    @require(lambda price: math.isfinite(price) and price > 0)
    @require(lambda quantity: quantity > 0)
    def apply(self, action: TradeAction, stock_id: str, price: float, quantity: int, *, now: datetime) -> TradeCost:
        gross = price * quantity
        fee = max(self.min_fee, int(gross * self.fee_rate))
        kind = SecurityKind.of(stock_id)
        tax_rate = self.tax_rate if kind == SecurityKind.STOCK else self.etf_tax_rate
        exempt = kind == SecurityKind.BOND_ETF and now.date() <= self.bond_etf_tax_exempt_until
        tax = int(gross * tax_rate) if action == TradeAction.SELL and not exempt else 0

        return TradeCost(action=action, gross=gross, fee=fee, tax=tax)


@dataclass(frozen=True)
class AffordableQuantityRule:
    """The largest lot-aligned BUY quantity whose gross plus fee fits in the cash."""

    cost_rule: TradingCostRule

    @require(lambda price: math.isfinite(price) and price > 0)
    @require(lambda lot_size: lot_size > 0)
    @ensure(lambda result, lot_size: result >= 0 and result % lot_size == 0)
    def apply(self, cash: float, stock_id: str, price: float, lot_size: int, *, now: datetime) -> int:
        # The fee is rounded down, so up to one dollar more than cash / (price * (1 + fee_rate)) can still fit.
        quantity = int((cash + 1) // (price * (1 + self.cost_rule.fee_rate))) // lot_size * lot_size

        while quantity > 0 and -self.cost_rule.apply(TradeAction.BUY, stock_id, price, quantity, now=now).net > cash:
            quantity -= lot_size

        return max(quantity, 0)
