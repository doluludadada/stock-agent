from typing import Protocol

from src.a_domain.model.trading.order import Order
from src.a_domain.model.trading.position import Position


class IBrokerPort(Protocol):
    """
    Interface for executing trades and retrieving account status.
    """

    async def place_order(self, order: Order) -> str:
        """
        Sends the order to the brokerage.
        Returns the Broker's Order ID (str) if successful.
        Raises exception on failure.
        """
        ...

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancels an existing order at the brokerage.
        """
        ...

    async def get_positions(self) -> list[Position]:
        """
        Retrieves current portfolio holdings.
        """
        ...

    async def get_cash_balance(self) -> float:
        """
        Returns available buying power.
        """
        ...
