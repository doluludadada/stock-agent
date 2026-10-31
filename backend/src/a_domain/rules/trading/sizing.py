import math
from dataclasses import dataclass
from datetime import datetime

from icontract import ensure, require

from a_domain.model.trading.account import Account
from a_domain.rules.trading.cost import AffordableQuantityRule, TradingCostRule
from a_domain.rules.trading.tick import LimitPriceRule
from a_domain.types.enums import TradeAction


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

    risk_per_trade_pct: float  # e.g. 0.02: risk 2% of equity per trade
    stop_loss_pct: float  # e.g. 0.10: the stop-loss sits 10% below entry
    lot_size: int
    limit_price_rule: LimitPriceRule
    affordable_quantity_rule: AffordableQuantityRule
    buy_cost_rule: BuyCostRule

    @require(lambda self: 0 < self.risk_per_trade_pct <= 1.0)
    @require(lambda self: 0 < self.stop_loss_pct < 1.0)
    @require(lambda self: self.lot_size > 0)
    @require(lambda price: price > 0, "Price must be executable")
    @require(lambda equity: math.isfinite(equity) and equity >= 0, "Equity must be a finite amount")
    @ensure(lambda result, self: result % self.lot_size == 0, "Must align with lot size")
    @ensure(
        lambda result, self, account, stock_id, price, now: (
            result == 0 or self.buy_cost_rule.apply(stock_id, price, result, now=now) <= account.cash
        )
    )
    def apply(self, account: Account, equity: float, stock_id: str, price: float, *, now: datetime) -> int:
        limit_price = self.limit_price_rule.apply(TradeAction.BUY, stock_id, price)
        risk_budget = equity * self.risk_per_trade_pct
        risk_per_share = limit_price * self.stop_loss_pct
        ideal_quantity = int(risk_budget // risk_per_share) // self.lot_size * self.lot_size
        affordable_quantity = self.affordable_quantity_rule.apply(
            cash=account.cash, stock_id=stock_id, price=limit_price, lot_size=self.lot_size, now=now
        )

        return min(ideal_quantity, affordable_quantity)
