from datetime import datetime
from typing import Annotated

from pydantic import Field, PositiveFloat, PositiveInt, validate_call
from pydantic.dataclasses import dataclass

from a_domain.model.trading.account import Account
from a_domain.rules.trading.cost import AffordableQuantityRule, TradingCostRule
from a_domain.rules.trading.tick import LimitPriceRule
from a_domain.types.enums import TradeAction
from a_domain.types.values import NonNegativeFiniteFloat, ProperFraction


@dataclass(frozen=True)
class BuyCostRule:
    """The cash a BUY decided at `price` can take: `quantity` shares at the order's limit (LimitPriceRule) plus the fee."""

    limit_price_rule: LimitPriceRule
    cost_rule: TradingCostRule

    def apply(self, stock_id: str, price: float, quantity: int, *, now: datetime) -> float:
        limit_price = self.limit_price_rule.apply(TradeAction.BUY, stock_id, price)

        return -self.cost_rule.apply(TradeAction.BUY, stock_id, limit_price, quantity, now=now).net


@dataclass(frozen=True)
class SizingRule:
    """
    BUY quantity: the risk budget, `risk_per_trade_pct` of the run's equity (EquityRule), divided by the loss per share
    at the stop-loss, capped by what the account's cash can pay for including the broker fee. Both are priced at the
    order's limit (LimitPriceRule), the most a share of the BUY can cost. The quantity is a multiple of `lot_size` shares.
    """

    risk_per_trade_pct: Annotated[float, Field(gt=0, le=1)]  # e.g. 0.02: risk 2% of equity per trade
    stop_loss_pct: ProperFraction  # e.g. 0.10: the stop-loss sits 10% below entry
    lot_size: PositiveInt
    limit_price_rule: LimitPriceRule
    affordable_quantity_rule: AffordableQuantityRule

    @validate_call
    def apply(self, account: Account, equity: NonNegativeFiniteFloat, stock_id: str, price: PositiveFloat, *, now: datetime) -> int:
        limit_price = self.limit_price_rule.apply(TradeAction.BUY, stock_id, price)
        risk_budget = equity * self.risk_per_trade_pct
        risk_per_share = limit_price * self.stop_loss_pct
        ideal_quantity = int(risk_budget // risk_per_share) // self.lot_size * self.lot_size
        affordable_quantity = self.affordable_quantity_rule.apply(
            cash=account.cash, stock_id=stock_id, price=limit_price, lot_size=self.lot_size, now=now
        )

        return min(ideal_quantity, affordable_quantity)
