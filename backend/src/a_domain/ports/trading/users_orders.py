from typing import Protocol

from a_domain.types.enums import ExecutionProvider


class IUsersOrders(Protocol):
    """
    The orders of every user of the site, counted: the answer names no user, no order and no stock, so a check of the
    whole site can weigh them without any user's data leaving that user's rows.
    """

    async def awaiting_settlement(self, broker: ExecutionProvider) -> int:
        """How many orders of every user's runs on `broker` await settlement (OrderStatus.awaits_settlement)."""
        ...
