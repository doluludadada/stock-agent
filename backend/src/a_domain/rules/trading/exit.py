from decimal import Decimal

from backend.src.a_domain.model.indicators.technical_indicators import Macd


class ExitRule:
    """
    Domain Rule: Determines when to close a position.
    """

    @staticmethod
    def should_stop_loss(current_price: Decimal, entry_price: Decimal, threshold_pct: float) -> bool:
        if entry_price == 0:
            return False
        stop_price = entry_price * (Decimal("1.0") - Decimal(str(threshold_pct)))
        return current_price <= stop_price

    @staticmethod
    def should_take_profit_technical(macd: Macd, close_price: Decimal, ma20: Decimal) -> bool:
        if macd.line is None or macd.signal is None:
            return False
        is_dead_cross = macd.line < macd.signal
        is_below_ma = close_price < ma20
        return is_dead_cross or is_below_ma
