# src\a_domain\rules\trading\action.py
from src.a_domain.types.enums import SignalAction


class ActionRule:
    """
    Rule: Maps a Score (0-100) to an Action (BUY/SELL/HOLD).
    """

    def __init__(self, buy_threshold: int = 70, sell_threshold: int = 30):
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def resolve(self, score: int) -> SignalAction:
        if score >= self.buy_threshold:
            return SignalAction.BUY
        elif score <= self.sell_threshold:
            return SignalAction.SELL
        else:
            return SignalAction.HOLD
