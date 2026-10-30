from typing import Protocol

from a_domain.model.trading.account import Account
from a_domain.model.trading.order import Order


class IExecutionProvider(Protocol):
    """
    A broker: accepts or refuses orders and reports the account. It writes no app records.

    place_order takes a PENDING order and returns it final: REJECTED (a pre-trade rule refused it),
    FILLED, CANCELLED (accepted, then not or not fully filled; any partial fill is recorded) or
    FAILED (technical error). The app sends IOC orders and keeps no working orders.
    """

    async def place_order(self, order: Order) -> Order: ...

    async def get_account(self) -> Account:
        """Cash and positions, read together."""
        ...
