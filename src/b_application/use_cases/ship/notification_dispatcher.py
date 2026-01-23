from src.a_domain.model.analysis.signal import TradeSignal
from src.a_domain.ports.system.logging_port import ILoggingPort
from src.a_domain.ports.system.notification_port import INotificationPort
from src.a_domain.types.enums import SignalAction
from src.b_application.configuration.schemas import AppConfig


class NotificationDispatcher:
    """
    Use Case: Send notifications for actionable signals.

    Responsibility:
    - Filter signals worth notifying (BUY/SELL only)
    - Dispatch alerts via NotificationPort
    """

    def __init__(
        self,
        notification_port: INotificationPort | None,
        config: AppConfig,
        logger: ILoggingPort,
    ):
        self._notification_port = notification_port
        self._config = config
        self._logger = logger

    async def execute(self, signals: list[TradeSignal]) -> int:
        """
        Send notifications for actionable signals.

        Args:
            signals: List of TradeSignal to potentially notify.

        Returns:
            Number of notifications sent successfully.
        """
        if not self._config.enable_notifications:
            self._logger.debug("Notifications disabled")
            return 0

        if not self._notification_port:
            self._logger.warning("Notification port not configured")
            return 0

        if not self._config.notification_recipients:
            self._logger.warning("No notification recipients configured")
            return 0

        # Filter to actionable signals only (BUY/SELL)
        actionable = [s for s in signals if s.action in (SignalAction.BUY, SignalAction.SELL)]

        if not actionable:
            self._logger.debug("No actionable signals to notify")
            return 0

        self._logger.info(f"Dispatching {len(actionable)} signal notifications")

        sent_count = 0
        for signal in actionable:
            try:
                success = await self._notification_port.send_signal_alert(
                    signal=signal,
                    recipients=self._config.notification_recipients,
                )
                if success:
                    sent_count += 1
            except Exception as e:
                self._logger.error(f"Failed to send notification for {signal.stock_id}: {e}")

        self._logger.success(f"Sent {sent_count}/{len(actionable)} notifications")
        return sent_count
