from src.a_domain.types.enums import SignalAction


class SignalActionResolver:
    """
    Rule: Determines the trade action (BUY/SELL/HOLD) based on the combined score.
    Pure domain logic with no private methods.
    """

    def __init__(self, buy_threshold: int = 70, sell_threshold: int = 30):
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def resolve(self, combined_score: int) -> SignalAction:
        if combined_score >= self.buy_threshold:
            return SignalAction.BUY
        elif combined_score <= self.sell_threshold:
            return SignalAction.SELL
        else:
            return SignalAction.HOLD
