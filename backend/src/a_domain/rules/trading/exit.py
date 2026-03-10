from a_domain.model.indicators.technical_indicators import Macd


class ExitRule:
    """Determines when to close a position."""

    @staticmethod
    def should_stop_loss(current_price: float, entry_price: float, threshold_pct: float) -> bool:
        if entry_price == 0:
            return False
        stop_price = entry_price * (1.0 - threshold_pct)
        return current_price <= stop_price

    @staticmethod
    def should_take_profit_technical(macd: Macd, close_price: float, ma20: float) -> bool:
        if macd.line is None or macd.signal is None:
            return False
        return macd.line < macd.signal or close_price < ma20
