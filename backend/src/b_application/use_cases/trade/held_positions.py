from collections.abc import Mapping

from a_domain.model.trading.account import Position
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.holding_repository import IHoldingRepository
from a_domain.types.enums import ExecutionProvider, HoldingSource


class HeldPositions:
    """
    Use Case: Read what the user holds under each source asked for, in the sources' order: the positions of each
    account as its broker lists them now (`accounts`, the user's), and the holdings entered by hand. A source it could
    not read is left out of the answer: an account the wiring did not give the user, a real broker while its login is
    down, or one whose answer fails. It never orders and records no run.
    """

    def __init__(
        self, holdings: IHoldingRepository, accounts: Mapping[ExecutionProvider, IExecutionProvider], logger: ILoggingProvider
    ) -> None:
        self._holdings = holdings
        self._accounts = accounts
        self._logger = logger

    async def execute(self, sources: frozenset[HoldingSource]) -> dict[HoldingSource, list[Position]]:
        held: dict[HoldingSource, list[Position]] = {}

        for source in (source for source in HoldingSource if source in sources):
            if source.broker is None:
                held[source] = await self._holdings.get_all()
                continue

            account = self._accounts.get(source.broker)

            if account is None or not account.link().up:
                continue

            try:
                held[source] = await account.open_positions()
            except RuntimeError as error:
                self._logger.warning(f"Holdings: the {source.broker.label} positions are unavailable: {error}")

        return held
