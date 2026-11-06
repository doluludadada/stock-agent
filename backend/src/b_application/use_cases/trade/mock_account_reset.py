from a_domain.model.trading.account import Account
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import ISimulatedExecutionProvider
from a_domain.types.values import PositiveFiniteFloat


class MockAccountReset:
    """
    Use Case: Open the user's mock account again with `initial_cash` and no positions. The account page, its equity
    curve and its trades start at the new opening, and every decision is open to follow again; no run, decision or
    order is deleted. It holds the user's mock book, a simulator, never the broker the Pipeline orders on, so no wiring
    can hand it a real account.
    """

    def __init__(self, mock_broker: ISimulatedExecutionProvider, market_clock: IMarketClock) -> None:
        self._mock_broker = mock_broker
        self._market_clock = market_clock

    async def execute(self, initial_cash: PositiveFiniteFloat) -> Account:
        return await self._mock_broker.reset(initial_cash, self._market_clock.now())
