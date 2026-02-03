from typing import Protocol

from backend.src.a_domain.model.trading.signal import TradeSignal


class INotificationProvider(Protocol):
    """Interface for sending trade signal notifications."""

    async def send_signal_alert(
        self,
        signal: TradeSignal,
        recipients: list[str],
    ) -> bool: ...


