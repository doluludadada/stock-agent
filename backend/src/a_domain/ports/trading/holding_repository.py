from typing import Protocol

from a_domain.model.trading.account import Position


class IHoldingRepository(Protocol):
    """
    The holdings one user entered by hand, one per stock: shares the user owns somewhere the site cannot read. They are
    no account: nothing orders on them, and no run reads them.
    """

    async def get_all(self) -> list[Position]:
        """Every holding, in stock id order, none of them marked."""
        ...

    async def save(self, position: Position) -> None:
        """Inserts the holding, or replaces the one of the same stock."""
        ...

    async def remove(self, stock_id: str) -> bool:
        """Deletes the stock's holding. False when there was none."""
        ...
