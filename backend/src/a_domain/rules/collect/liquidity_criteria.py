from dataclasses import dataclass


@dataclass
class LiquidityCriteria:
    """
    Rule: Filters liquidity traps.
    """

    min_daily_volume: int
    min_price: float

    def is_liquid_enough(self, price: float, volume: int) -> bool:
        return price >= self.min_price and volume >= self.min_daily_volume
