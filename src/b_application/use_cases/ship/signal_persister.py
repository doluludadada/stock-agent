from src.a_domain.model.trading.signal import TradeSignal
from src.a_domain.ports.analysis.signal_repository import ISignalRepository
from src.a_domain.ports.system.logging_provider import ILoggingProvider


class SignalPersister:
    """
    Use Case: Persist trade signals to repository.

    Responsibility:
    - Save signals to persistent storage
    - Handle batch operations efficiently
    """

    def __init__(
        self,
        signal_repo: ISignalRepository,
        logger: ILoggingProvider,
    ):
        self._signal_repo = signal_repo
        self._logger = logger

    async def execute(self, signals: list[TradeSignal]) -> None:
        """
        Persist all signals to repository.

        Args:
            signals: List of TradeSignal to persist.
        """
        if not signals:
            self._logger.debug("No signals to persist")
            return

        self._logger.info(f"Persisting {len(signals)} signals to repository")

        try:
            await self._signal_repo.save_batch(signals)
            self._logger.success(f"Successfully persisted {len(signals)} signals")
        except Exception as e:
            self._logger.error(f"Failed to persist signals: {e}")
            raise
