from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.notification_provider import INotificationProvider
from a_domain.types.enums import TradeAction
from b_application.schemas.config import AppConfig


class Reporting:
    def __init__(
        self, notification_provider: INotificationProvider | None, config: AppConfig, logger: ILoggingProvider
    ):
        self._notification = notification_provider
        self._config = config
        self._logger = logger

    async def execute(self, signals: list[TradeSignal]) -> None:
        if (
            not self._config.notifications.enabled
            or not self._notification
            or not self._config.notifications.recipients
        ):
            return

        actionable = [s for s in signals if s.action in (TradeAction.BUY, TradeAction.SELL)]
        if not actionable:
            return

        for signal in actionable:
            try:
                await self._notification.send_signal_alert(
                    signal=signal, recipients=self._config.notifications.recipients
                )
            except Exception as e:
                self._logger.error(f"Failed to notify for {signal.stock_id}: {e}")
