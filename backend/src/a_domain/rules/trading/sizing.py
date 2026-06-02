from dataclasses import dataclass

from a_domain.model.trading.account import Account


@dataclass(frozen=True)
class SizingRule:
    """
    Calculates BUY quantity.

    In this first version, account.cash means currently usable cash.
    This is position sizing, not true risk-based sizing.
    """

    """
    TODO:
    
    你現在不是做真正的 risk sizing。真正的 risk sizing 會需要：

    entry_price
    stop_loss_price
    risk_per_share
    max_loss_amount

    你現在這版比較像：
    我每次最多用 cash 的幾 % 去買
    
    """

    position_pct: float
    """
    Fraction of currently usable cash allocated to one new position.
    - Example: 0.02 means using 2% of account.cash.
    """

    lot_size: int = 1
    """
    Minimum trading unit.
    - Use 1 for normal share-based sizing.
    - Use 1000 if the market requires board-lot trading.
    """
    def calculate(self, account: Account, price: float) -> int:
        if account.cash <= 0:
            return 0

        if price <= 0:
            return 0

        if self.position_pct <= 0:
            return 0

        if self.lot_size <= 0:
            return 0

        budget = account.cash * self.position_pct
        quantity = int(budget // price)

        return (quantity // self.lot_size) * self.lot_size