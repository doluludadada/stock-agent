from a_domain.model.trading.account import Account
from a_domain.model.trading.order import Order
from a_domain.ports.trading.execution_provider import IExecutionProvider


class ShioajiExecutionProvider(IExecutionProvider):
    """
    Real broker adapter, not implemented (US-301 in docs/requirements.md); create_execution_provider refuses SHIOAJI.

    place_order must return the order final, with each execution recorded through Order.fill using the
    fee and tax the broker charged, so the app's `orders` table gets the same audit trail as the mock.
    """

    async def place_order(self, order: Order) -> Order:
        raise NotImplementedError

    async def get_account(self) -> Account:
        raise NotImplementedError
