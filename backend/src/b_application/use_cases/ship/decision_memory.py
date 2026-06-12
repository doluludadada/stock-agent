from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.pipeline_status import PipelineStatus


class DecisionMemory:
    """
    Saves generated trading decisions for future AI context.
    """

    def __init__(
        self,
        knowledge_repository: IKnowledgeRepository,
        logger: ILoggingProvider,
    ) -> None:
        self._knowledge_repository = knowledge_repository
        self._logger = logger

    async def execute(self, status: PipelineStatus) -> None:
        for signal in status.signals:
            try:
                stock = status.stocks_cache.get(signal.stock_id)

                if stock is None:
                    self._logger.warning(f"Decision memory skipped. Stock not found: {signal.stock_id}")
                    continue

                await self._knowledge_repository.save_decision(
                    stock=stock,
                    signal=signal,
                )

            except Exception as error:
                message = f"Decision memory failed for {signal.stock_id}: {error}"
                self._logger.error(message)
                status.stats.add_error(message)
