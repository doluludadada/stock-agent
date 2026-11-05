from typing import Protocol

from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal


class IKnowledgeRepository(Protocol):
    """
    Stores one owner's trading decisions and returns a stock's own decision history as AI context. Another owner's
    decisions are never returned.
    """

    async def find_decision_history(self, stock_id: str, limit: int = 3) -> str:
        """Returns the newest saved decisions for this stock only, or an empty string."""
        ...

    async def save_decision(self, stock: Stock, signal: TradeSignal) -> None: ...

    def describe_decision(self, stock: Stock, signal: TradeSignal) -> str:
        """The decision and its evidence as the text the AI later reads back in the stock's decision history."""
        ...
