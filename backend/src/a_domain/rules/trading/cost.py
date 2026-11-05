from datetime import date, datetime
from typing import Literal

from pydantic import NonNegativeFloat, NonNegativeInt, PositiveInt, validate_call
from pydantic.dataclasses import dataclass

from a_domain.types.enums import SecurityKind, TradeAction
from a_domain.types.values import PositiveFiniteFloat


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


@dataclass(frozen=True)
class TradingCostRule:
    """
    Single source of truth for the broker fee (with its minimum) and the securities transaction tax.
    The tax is charged on a SELL only: `tax_rate` for a stock and `etf_tax_rate` for an ETF (SecurityKind). A bond ETF
    traded on or before `bond_etf_tax_exempt_until` pays none, and `etf_tax_rate` after it. The trading date is the date
    of `now`, the trade's time, in its own zone; every Taiwan trading hour falls on the same date in UTC and in Taipei.
    """

    fee_rate: NonNegativeFloat
    tax_rate: NonNegativeFloat
    etf_tax_rate: NonNegativeFloat
    min_fee: NonNegativeInt
    bond_etf_tax_exempt_until: date

    @validate_call
    def apply(
        self,
        action: Literal[TradeAction.BUY, TradeAction.SELL],
        stock_id: str,
        price: PositiveFiniteFloat,
        quantity: PositiveInt,
        *,
        now: datetime,
    ) -> TradeCost:
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

    @validate_call
    def apply(self, cash: float, stock_id: str, price: PositiveFiniteFloat, lot_size: PositiveInt, *, now: datetime) -> int:
        # The fee is rounded down, so up to one dollar more than cash / (price * (1 + fee_rate)) can still fit.
        quantity = int((cash + 1) // (price * (1 + self.cost_rule.fee_rate))) // lot_size * lot_size

        while quantity > 0 and -self.cost_rule.apply(TradeAction.BUY, stock_id, price, quantity, now=now).net > cash:
            quantity -= lot_size

        return max(quantity, 0)
