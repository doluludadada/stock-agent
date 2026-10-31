from dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.trading.position import Position


@dataclass(frozen=True)
class PositionValuation:
    position: Position
    mark: Ohlcv | None
    """The bar whose close prices the position; its ts is the price time shown. None: no price, valued at average cost."""

    unrealized_pnl: float
    """Net proceeds of selling everything at the mark (fee and tax deducted) minus the cost basis. 0 when unmarked."""

    @property
    def market_value(self) -> float:
        return self.position.quantity * (self.mark.close if self.mark else self.position.average_cost)
