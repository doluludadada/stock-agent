from a_domain.model.trading.account import Account
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from b_application.schemas.pipeline_context import PipelineContext


class AccountLoader:
    """Use Case: Load current account snapshot into PipelineContext."""

    def __init__(
        self,
        execution_provider: IExecutionProvider,
        logger: ILoggingProvider,
    ):
        self._execution_provider = execution_provider
        self._logger = logger

    async def execute(self, workflow_state: PipelineContext) -> None:
        cash = await self._execution_provider.get_cash_balance()
        positions = await self._execution_provider.get_positions()

        workflow_state.account = Account(
            cash=cash,
            positions=positions,
        )

        self._logger.info(f"Account loaded. Cash={cash}, Positions={len(positions)}")
