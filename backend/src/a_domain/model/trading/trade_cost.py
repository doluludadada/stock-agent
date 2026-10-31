from dataclasses import dataclass

from a_domain.types.enums import TradeAction


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
