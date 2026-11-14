from datetime import date

from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Position
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.holding_repository import IHoldingRepository


class HoldingEntry:
    """
    Use Case: Keep a holding the user enters by hand: shares of a listed stock at their average cost, bought on
    `opened_on` when the user says so, stamped at that day's session close. It replaces the user's earlier entry of the
    same stock. It is a note of what the user owns elsewhere: it orders nothing and touches no account.
    """

    def __init__(self, holdings: IHoldingRepository, market_clock: IMarketClock) -> None:
        self._holdings = holdings
        self._market_clock = market_clock

    async def execute(self, stock: Stock, quantity: int, average_cost: float, opened_on: date | None) -> Position:
        position = Position(
            stock_id=stock.stock_id,
            quantity=quantity,
            average_cost=average_cost,
            opened_at=None if opened_on is None else self._market_clock.session_close(opened_on),
        )
        await self._holdings.save(position)

        return position
