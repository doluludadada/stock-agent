from typing import Protocol

from src.a_domain.model.analysis.signal import TradeSignal


class INotificationPort(Protocol):
    """Interface for sending trade signal notifications."""

    async def send_signal_alert(
        self,
        signal: TradeSignal,
        recipients: list[str],
    ) -> bool: ...
