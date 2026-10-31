from typing import override

import httpx

from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.notification_provider import INotificationProvider
from a_domain.types.enums import TradeAction
from b_application.config.app_config import AppConfig


class LineNotificationAdapter(INotificationProvider):
    """
    Pushes trading signals to LINE users via the Messaging API.
    """

    def __init__(self, config: AppConfig, logger: ILoggingProvider):
        self._logger = logger
        self._token = config.line.channel_access_token
        self._multicast_url = config.sources.line.multicast_url
        self._timeout_seconds = config.sources.line.multicast_timeout_seconds

    @override
    async def send_signal_alert(self, signal: TradeSignal, recipients: list[str]) -> bool:
        if not self._token:
            self._logger.warning("LINE token is missing. Cannot send notification.")
            return False

        if not recipients:
            return False

        emoji = "🟢" if signal.action == TradeAction.BUY else "🔴"
        alert = (
            f"{emoji} TW-Stock-Agent Alert\n──────────────\nAction : {signal.action.value}\nStock  : {signal.stock_id}\n"
            f"Price  : {signal.price_at_signal}\nVolume : {signal.quantity} shares\nScore  : {signal.score}/100\n"
            f"──────────────\nReason : {signal.reason}"
        )
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        payload = {"to": recipients, "messages": [{"type": "text", "text": alert}]}

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            try:
                response = await client.post(self._multicast_url, headers=headers, json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                self._logger.error(f"Failed to send LINE alert. Status: {error.response.status_code}, Body: {error.response.text}")
                return False
            except Exception as error:
                self._logger.error(f"Unexpected error sending LINE alert: {error}")
                return False

        self._logger.success(f"Successfully sent LINE alert for {signal.stock_id} to {len(recipients)} users.")
        return True
