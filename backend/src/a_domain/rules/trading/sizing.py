class SizingRule:
    """Calculates quantity based on Risk Management."""

    @staticmethod
    def calculate_quantity(capital: float, price: float, risk_per_trade_pct: float) -> int:
        if price <= 0:
            return 0
        allocation = capital * risk_per_trade_pct
        return int(allocation / price)
