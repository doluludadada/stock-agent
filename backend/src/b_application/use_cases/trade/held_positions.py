from typing import Any

from a_domain.model.trading.account import Position
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IBrokerExecutionProvider, IExecutionProvider
from a_domain.ports.trading.holding_repository import IHoldingRepository
from a_domain.types.enums import HoldingSource


class HeldPositions:
    """
    Use Case: Read what the user holds under each source asked for: the real broker's positions as it lists them now,
    the mock account's, and the holdings entered by hand. A source it could not read is left out of the answer: the
    real broker for a user the wiring gave none (`brokerage` is None), while its login is down, or when its answer
    fails. It never orders and records no run.
    """

    def __init__(
        self,
        holdings: IHoldingRepository,
        mock_broker: IExecutionProvider,
        brokerage: IBrokerExecutionProvider[Any, Any] | None,
        logger: ILoggingProvider,
    ) -> None:
        self._holdings = holdings
        self._mock_broker = mock_broker
        self._brokerage = brokerage
        self._logger = logger

    async def execute(self, sources: frozenset[HoldingSource]) -> dict[HoldingSource, list[Position]]:
        held: dict[HoldingSource, list[Position]] = {}

        if HoldingSource.BROKERAGE in sources and self._brokerage is not None and self._brokerage.link().up:
            try:
                held[HoldingSource.BROKERAGE] = await self._brokerage.open_positions()
            except RuntimeError as error:
                self._logger.warning(f"Holdings: the broker's positions are unavailable: {error}")

        if HoldingSource.MOCK in sources:
            held[HoldingSource.MOCK] = (await self._mock_broker.get_account()).positions

        if HoldingSource.MANUAL in sources:
            held[HoldingSource.MANUAL] = await self._holdings.get_all()

        return held
