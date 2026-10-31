from dataclasses import dataclass

from a_domain.model.trading.position_valuation import PositionValuation


@dataclass(frozen=True)
class AccountValuation:
    cash: float
    positions: list[PositionValuation]

    @property
    def market_value(self) -> float:
        return sum(position.market_value for position in self.positions)

    @property
    def unrealized_pnl(self) -> float:
        return sum(position.unrealized_pnl for position in self.positions)

    @property
    def equity(self) -> float:
        return self.cash + self.market_value
