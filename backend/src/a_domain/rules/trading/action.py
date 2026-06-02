from dataclasses import dataclass

from a_domain.types.enums import TradeAction


@dataclass(frozen=True)
class ActionRule:
    """
    Maps a score into BUY / HOLD / SELL.
    """


    buy_threshold: int = 70
    """
    Default fallback for local tests.
    - NOTE: Production values should be injected from AppConfig.
    """

    sell_threshold: int = 30
    """
    Default fallback for local tests.
    - Production values should be injected from AppConfig.
    """
    def resolve(self, score: int) -> TradeAction:
        if score >= self.buy_threshold:
            return TradeAction.BUY

        if score <= self.sell_threshold:
            return TradeAction.SELL

        return TradeAction.HOLD
