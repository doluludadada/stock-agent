# backend/src/a_domain/ports/system/market_clock.py

from datetime import date, datetime
from typing import Protocol

from a_domain.types.enums import TradingPhase


class IMarketClock(Protocol):
    """The exchange's local clock. Every time the trading code compares against comes from here."""

    def now(self) -> datetime: ...

    def today(self) -> date: ...

    def to_market_datetime(self, value: datetime) -> datetime:
        """An aware datetime in the exchange's zone. A naive one is read as exchange-local wall-clock time."""
        ...

    def to_trading_date(self, value: datetime) -> date: ...

    def history_window(self, lookback_days: int) -> tuple[datetime, datetime]: ...

    def session_close_after(self, value: datetime, sessions: int) -> datetime:
        """
        The close of the `sessions`-th weekday session that opens after `value`: Friday evening and 1 give Monday's close.
        Exchange holidays are not modelled.
        """
        ...

    def last_closed_session(self) -> date:
        """The latest weekday whose session has closed: the newest daily bar that can exist. Exchange holidays are not modelled."""
        ...

    def last_settled_session(self) -> date:
        """
        The latest weekday session whose daily bar is final in every price source, which happens a while after its close.
        Exchange holidays are not modelled.
        """
        ...

    def trading_phase(self) -> TradingPhase:
        """Where the exchange's trading day stands now. Exchange holidays and a delayed open or close are not modelled."""
        ...
