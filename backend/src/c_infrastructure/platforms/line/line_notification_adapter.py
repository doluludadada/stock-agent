# backend/src/c_infrastructure/platforms/line/line_notification_adapter.py
import httpx

from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.notification_provider import INotificationProvider
from b_application.schemas.config import AppConfig


class LineNotificationAdapter(INotificationProvider):
    """
    Pushes trading signals to LINE users via the Messaging API.
    """

    MULTICAST_URL = "https://api.line.me/v2/bot/message/multicast"

    def __init__(self, config: AppConfig, logger: ILoggingProvider):
        self._config = config
        self._logger = logger
        self._token = self._config.line.channel_access_token

    async def send_signal_alert(self, signal: TradeSignal, recipients: list[str]) -> bool:
        if not self._token:
            self._logger.warning("LINE token is missing. Cannot send notification.")
            return False

        if not recipients:
            return False

        # Format a beautiful message for the user
        emoji = "🟢" if signal.action.value == "BUY" else "🔴"
        message_text = (
            f"{emoji} TW-Stock-Agent Alert\n"
            f"──────────────\n"
            f"Action : {signal.action.value}\n"
            f"Stock  : {signal.stock_id}\n"
            f"Price  : {signal.price_at_signal}\n"
            f"Volume : {signal.quantity} shares\n"
            f"Score  : {signal.score}/100\n"
            f"──────────────\n"
            f"Reason : {signal.reason}"
        )

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        payload = {"to": recipients, "messages": [{"type": "text", "text": message_text}]}

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(self.MULTICAST_URL, headers=headers, json=payload)
                resp.raise_for_status()
                self._logger.success(f"Successfully sent LINE alert for {signal.stock_id} to {len(recipients)} users.")
                return True
            except httpx.HTTPStatusError as e:
                self._logger.error(f"Failed to send LINE alert. Status: {e.response.status_code}, Body: {e.response.text}")
                return False
            except Exception as e:
                self._logger.error(f"Unexpected error sending LINE alert: {e}")
                return False
