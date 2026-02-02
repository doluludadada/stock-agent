# src\a_domain\rules\trading\exit.py
from decimal import Decimal

from src.a_domain.model.indicators.macd import Macd


class ExitRule:
    """
    Domain Rule: Determines when to close a position.
    Used by: MonitorPositions (Application Layer)
    """

    @staticmethod
    def should_stop_loss(current_price: Decimal, entry_price: Decimal, threshold_pct: float) -> bool:
        """
        True if price drops below entry * (1 - threshold).
        """
        if entry_price == 0:
            return False
        stop_price = entry_price * (Decimal("1.0") - Decimal(str(threshold_pct)))
        return current_price <= stop_price

    @staticmethod
    def should_take_profit_technical(macd: Macd, close_price: Decimal, ma20: Decimal) -> bool:
        """
        True if Technicals deteriorate (Dead Cross OR Price < MA20).
        """
        if macd.line is None or macd.signal is None:
            return False

        is_dead_cross = macd.line < macd.signal
        is_below_ma = close_price < ma20

        return is_dead_cross or is_below_ma
