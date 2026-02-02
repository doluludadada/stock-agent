"""
Use Case: Send notifications for actionable signals.

Only notifies for BUY/SELL signals, not HOLD.
"""
from src.a_domain.model.trading.signal import TradeSignal
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.a_domain.ports.system.notification_provider import INotificationProvider
from src.a_domain.types.enums import SignalAction
from src.b_application.schemas.config import AppConfig


class SendNotifications:
    """
    Dispatches notifications for actionable trade signals.
    
    Only sends notifications for BUY and SELL signals.
    HOLD signals are not worth notifying about.
    """

    def __init__(
        self,
        notification_provider: INotificationProvider | None,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._notification = notification_provider
        self._config = config
        self._logger = logger

    async def execute(self, signals: list[TradeSignal]) -> int:
        """
        Send notifications for actionable signals.
        
        Returns:
            Number of notifications sent successfully.
        """
        if not self._config.enable_notifications:
            self._logger.debug("Notifications disabled")
            return 0

        if not self._notification:
            self._logger.warning("Notification provider not configured")
            return 0

        if not self._config.notification_recipients:
            self._logger.warning("No notification recipients configured")
            return 0

        # Filter to actionable signals only
        actionable = [s for s in signals if s.action in (SignalAction.BUY, SignalAction.SELL)]

        if not actionable:
            self._logger.debug("No actionable signals to notify")
            return 0

        self._logger.info(f"Sending {len(actionable)} notifications...")

        sent_count = 0
        for signal in actionable:
            try:
                success = await self._notification.send_signal_alert(
                    signal=signal,
                    recipients=self._config.notification_recipients,
                )
                if success:
                    sent_count += 1
            except Exception as e:
                self._logger.error(f"Failed to notify for {signal.stock_id}: {e}")

        self._logger.success(f"Sent {sent_count}/{len(actionable)} notifications")
        return sent_count
