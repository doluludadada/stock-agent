from backend.src.a_domain.model.trading.signal import TradeSignal
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.ports.system.notification_provider import INotificationProvider
from backend.src.a_domain.types.enums import SignalAction
from backend.src.b_application.schemas.config import AppConfig


class SendNotifications:
    def __init__(
        self, notification_provider: INotificationProvider | None, config: AppConfig, logger: ILoggingProvider
    ):
        self._notification = notification_provider
        self._config = config
        self._logger = logger

    async def execute(self, signals: list[TradeSignal]) -> int:
        if not self._config.enable_notifications or not self._notification or not self._config.notification_recipients:
            return 0
        actionable = [s for s in signals if s.action in (SignalAction.BUY, SignalAction.SELL)]
        if not actionable:
            return 0
        sent = 0
        for signal in actionable:
            try:
                if await self._notification.send_signal_alert(
                    signal=signal, recipients=self._config.notification_recipients
                ):
                    sent += 1
            except Exception as e:
                self._logger.error(f"Failed to notify for {signal.stock_id}: {e}")
        return sent
