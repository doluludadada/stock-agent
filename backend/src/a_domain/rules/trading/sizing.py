from dataclasses import dataclass

from icontract import ensure, require

from a_domain.model.trading.account import Account


# TODO: 
@dataclass(frozen=True)
class SizingRule:
    risk_per_trade_pct: float  # e.g., 0.02 (Risk 2% of total cash per trade)
    stop_loss_pct: float  # e.g., 0.10 (Stop loss set at 10% below entry)
    lot_size: int = 1

    @require(lambda self: 0 < self.risk_per_trade_pct <= 1.0)
    @require(lambda self: 0 < self.stop_loss_pct < 1.0)
    @require(lambda self: self.lot_size > 0)
    @require(lambda price: price > 0, "Price must be executable")
    @ensure(lambda result, self: result % self.lot_size == 0, "Must align with lot size")
    @ensure(lambda result: result >= 0)
    def calculate(self, account: Account, price: float) -> int:
        if account.cash <= 0:
            return 0

        # Formula: Risk Budget = Cash * Risk %
        risk_budget = account.cash * self.risk_per_trade_pct

        # Formula: Potential loss per share = Price * Stop Loss %
        risk_per_share = price * self.stop_loss_pct

        # Ideal quantity based on risk tolerance
        ideal_quantity = int(risk_budget // risk_per_share)

        # Safety Gate: Total order value must never exceed actual available cash
        max_qty_by_cash = int(account.cash // price)
        quantity = min(ideal_quantity, max_qty_by_cash)

        return (quantity // self.lot_size) * self.lot_size
