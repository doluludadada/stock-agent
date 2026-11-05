from collections.abc import Mapping, Sequence

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider


class DecisionMemory:
    """
    Saves each trading decision of the run, with the stock it was made on, for future AI context.
    """

    def __init__(self, knowledge_repository: IKnowledgeRepository, logger: ILoggingProvider) -> None:
        self._knowledge_repository = knowledge_repository
        self._logger = logger

    async def execute(self, signals: Sequence[TradeSignal], stocks: Mapping[str, Stock], stats: SystemStats) -> None:
        for signal in signals:
            try:
                stock = stocks.get(signal.stock_id)

                if stock is None:
                    self._logger.warning(f"Decision memory skipped. Stock not found: {signal.stock_id}")
                    continue

                await self._knowledge_repository.save_decision(stock=stock, signal=signal)

            except Exception as error:
                message = f"Decision memory failed for {signal.stock_id}: {error}"
                self._logger.error(message)
                stats.add_error(message)
