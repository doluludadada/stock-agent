from dataclasses import dataclass

from icontract import ensure, require

from a_domain.model.trading.account import Account
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.tick import TickRule
from a_domain.types.enums import TradeAction


@dataclass(frozen=True)
class SizingRule:
    """
    BUY quantity: the risk budget divided by the loss per share at the stop-loss, capped by what
    the cash can pay for including the broker fee. Both are priced at the order's limit (TickRule),
    the most a share of the BUY can cost.
    """

    risk_per_trade_pct: float  # e.g. 0.02: risk 2% of cash per trade
    stop_loss_pct: float  # e.g. 0.10: the stop-loss sits 10% below entry
    cost_rule: TradingCostRule
    lot_size: int = 1

    @require(lambda self: 0 < self.risk_per_trade_pct <= 1.0)
    @require(lambda self: 0 < self.stop_loss_pct < 1.0)
    @require(lambda self: self.lot_size > 0)
    @require(lambda price: price > 0, "Price must be executable")
    @ensure(lambda result, self: result % self.lot_size == 0, "Must align with lot size")
    @ensure(lambda result, self, account, stock_id, price: result == 0 or self.buy_cost(stock_id, price, result) <= account.cash)
    def calculate(self, account: Account, stock_id: str, price: float) -> int:
        limit_price = TickRule.limit_price(TradeAction.BUY, stock_id, price)
        risk_budget = account.cash * self.risk_per_trade_pct
        risk_per_share = limit_price * self.stop_loss_pct
        ideal_quantity = int(risk_budget // risk_per_share) // self.lot_size * self.lot_size
        affordable_quantity = self.cost_rule.max_buy_quantity(
            cash=account.cash, stock_id=stock_id, price=limit_price, lot_size=self.lot_size
        )

        return min(ideal_quantity, affordable_quantity)

    def buy_cost(self, stock_id: str, price: float, quantity: int) -> float:
        """The cash a BUY decided at `price` can take: `quantity` shares at the order's limit plus the fee."""
        return -self.cost_rule.cost_of(TradeAction.BUY, stock_id, TickRule.limit_price(TradeAction.BUY, stock_id, price), quantity).net
