from a_domain.types.enums import TradeAction


class ActionRule:
    """Maps a Score (0-100) to an Action (BUY/SELL/HOLD)."""

    def __init__(self, buy_threshold: int = 70, sell_threshold: int = 30):
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def resolve(self, score: int) -> TradeAction:
        if score >= self.buy_threshold:
            return TradeAction.BUY
        elif score <= self.sell_threshold:
            return TradeAction.SELL
        else:
            return TradeAction.HOLD
