from dataclasses import dataclass


@dataclass
class SocialBuzzCriteria:
    """
    Rule: Defines trending thresholds.
    """

    min_mentions: int
    min_push_count: int

    def is_trending(self, mention_count: int, push_sum: int) -> bool:
        return mention_count >= self.min_mentions or push_sum >= self.min_push_count


@dataclass
class LiquidityCriteria:
    """
    Rule: Filters liquidity traps.
    """

    min_daily_volume: int
    min_price: float

    def is_liquid_enough(self, price: float, volume: int) -> bool:
        return price >= self.min_price and volume >= self.min_daily_volume
