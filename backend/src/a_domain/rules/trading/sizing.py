# src\a_domain\rules\trading\sizing.py
from decimal import ROUND_DOWN, Decimal


class SizingRule:
    """
    Domain Rule: Calculates quantity based on Risk Management.
    Used by: SignalGenerator (Application Layer)
    """

    @staticmethod
    def calculate_quantity(capital: Decimal, price: Decimal, risk_per_trade_pct: float) -> int:
        """
        Simple Sizing: Allocate a fixed % of total capital to this trade.
        """
        if price <= 0:
            return 0

        allocation = capital * Decimal(str(risk_per_trade_pct))
        quantity = allocation / price

        # Round down to nearest integer (Standard TW stock lot logic can be applied here later)
        return int(quantity.to_integral_value(rounding=ROUND_DOWN))


