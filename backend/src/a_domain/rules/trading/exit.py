from dataclasses import dataclass
from datetime import datetime

from a_domain.model.indicators.technical_indicators import Macd
from a_domain.model.trading.signal import TradeSignal
from a_domain.types.enums import SignalReason, SignalSource, TradeAction


@dataclass(frozen=True)
class ExitRule:
    """Determines when to close a position and builds the exit signal."""

    stop_loss_pct: float

    def should_stop_loss(self, current_price: float, entry_price: float) -> bool:
        if entry_price == 0:
            return False
        stop_price = entry_price * (1.0 - self.stop_loss_pct)
        return current_price <= stop_price

    def build_stop_loss_signal(self, stock_id: str, price: float, quantity: int) -> TradeSignal:
        return TradeSignal(
            stock_id=stock_id,
            action=TradeAction.SELL,
            price_at_signal=price,
            source=SignalSource.TECHNICAL,
            score=0,
            reason=SignalReason.STOP_LOSS,
            quantity=quantity,
            generated_at=datetime.now(),
        )

    @staticmethod
    def should_take_profit_technical(macd: Macd, close_price: float, ma20: float) -> bool:
        if macd.line is None or macd.signal is None:
            return False
        return macd.line < macd.signal or close_price < ma20
