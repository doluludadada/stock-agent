# backend/src/a_domain/ports/system/market_clock.py

from datetime import date, datetime
from typing import Protocol


class IMarketClock(Protocol):
    """The exchange's local clock. Every time the trading code compares against comes from here."""

    def now(self) -> datetime: ...

    def today(self) -> date: ...

    def to_market_datetime(self, value: datetime) -> datetime:
        """An aware datetime in the exchange's zone. A naive one is read as exchange-local wall-clock time."""
        ...

    def to_trading_date(self, value: datetime) -> date: ...

    def history_window(self, lookback_days: int) -> tuple[datetime, datetime]: ...

    def last_closed_session(self) -> date:
        """The latest weekday whose session has closed: the newest daily bar that can exist. Exchange holidays are not modelled."""
        ...

    def is_market_open(self) -> bool: ...
