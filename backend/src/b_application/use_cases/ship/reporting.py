# backend/src/b_application/use_cases/ship/reporting.py

from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.notification_provider import INotificationProvider
from a_domain.types.enums import TradeAction
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class Reporting:
    """
    Use Case: Send final trade notifications.
        - Reporting is a notification side effect.
        - It must not execute orders, change signal decisions, or mutate order counts.
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

    async def execute(self, status: PipelineStatus) -> None:
        if not self._config.notifications.enabled:
            self._logger.info("Notifications disabled.")
            return

        if self._notification is None:
            self._logger.warning("Notification provider is not configured.")
            return

        # LINE user IDs or notification recipients configured for trade alerts.
        recipients = self._config.notifications.recipients

        if not recipients:
            self._logger.warning("Notification recipients are empty.")
            return

        signals = status.signals
        # Only BUY and SELL are pushed to users.
        # HOLD is persisted but not pushed to avoid noisy alerts.

        for signal in signals:
            if signal.action == TradeAction.HOLD:
                continue

            try:
                sent = await self._notification.send_signal_alert(signal, recipients)

                if sent:
                    self._logger.info(f"Notification sent: {signal.action.value} {signal.stock_id}")
                else:
                    self._logger.warning(f"Notification skipped or failed: {signal.action.value} {signal.stock_id}")

            except Exception as e:
                error_message = f"Notification failed for {signal.stock_id}: {e}"
                self._logger.error(error_message)
                status.stats.add_error(error_message)
