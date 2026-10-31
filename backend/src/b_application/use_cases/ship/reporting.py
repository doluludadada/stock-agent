from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.notification_provider import INotificationProvider
from a_domain.types.enums import TradeAction
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class Reporting:
    """
    Use Case: Send final trade notifications to the configured recipients (LINE user ids).
        - Reporting is a notification side effect.
        - It must not execute orders, change signal decisions, or mutate order counts.
        - Only BUY and SELL are pushed; HOLD is recorded but not pushed, to avoid noisy alerts.
    """

    def __init__(self, notification_provider: INotificationProvider | None, config: AppConfig, logger: ILoggingProvider) -> None:
        self._notification = notification_provider
        self._enabled = config.notifications.enabled
        self._recipients = config.notifications.recipients
        self._logger = logger

    async def execute(self, status: PipelineStatus) -> None:
        if not self._enabled:
            self._logger.info("Notifications disabled.")
            return

        if self._notification is None:
            self._logger.warning("Notification provider is not configured.")
            return

        if not self._recipients:
            self._logger.warning("Notification recipients are empty.")
            return

        for signal in [signal for signal in status.signals if signal.action != TradeAction.HOLD]:
            try:
                sent = await self._notification.send_signal_alert(signal, self._recipients)
            except Exception as error:
                self._logger.error(status.stats.add_error(f"Notification failed for {signal.stock_id}: {error}"))
                continue

            if sent:
                self._logger.info(f"Notification sent: {signal.action.value} {signal.stock_id}")
            else:
                self._logger.warning(f"Notification skipped or failed: {signal.action.value} {signal.stock_id}")
