from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.ports.trading.execution_provider import IExecutionProvider


class ShioajiExecutionProvider(IExecutionProvider):
    """
    Future real broker adapter.

    TODO:

    - Login to Shioaji.
    - Load real cash balance.
    - Load real positions.
    - Convert domain Order to Shioaji order.
    - Submit real order.
    - Map broker response back to domain.
    """

    async def place_order(self, order: Order) -> str:
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    async def get_positions(self) -> list[Position]:
        raise NotImplementedError

    async def get_cash_balance(self) -> float:
        raise NotImplementedError
