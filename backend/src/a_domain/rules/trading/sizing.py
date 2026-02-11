from decimal import ROUND_DOWN, Decimal


class SizingRule:
    """Calculates quantity based on Risk Management."""

    @staticmethod
    def calculate_quantity(capital: Decimal, price: Decimal, risk_per_trade_pct: float) -> int:
        if price <= 0:
            return 0
        allocation = capital * Decimal(str(risk_per_trade_pct))
        quantity = allocation / price
        return int(quantity.to_integral_value(rounding=ROUND_DOWN))
