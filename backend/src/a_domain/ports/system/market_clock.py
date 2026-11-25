from datetime import date, datetime, time, timedelta
from typing import Protocol

from a_domain.types.enums import TradingPhase


class IMarketClock(Protocol):
    """The exchange's local clock. Every time the trading code compares against comes from here."""

    def now(self) -> datetime: ...

    def today(self) -> date: ...

    def to_market_datetime(self, value: datetime) -> datetime:
        """The same instant in the exchange's zone, for code that shows its wall-clock time."""
        ...

    def to_trading_date(self, value: datetime) -> date: ...

    def session_close(self, session: date) -> datetime:
        """When that day's session closes, in the exchange's zone. A daily bar is stamped with it."""
        ...

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

    def last_market_time(self, at: time) -> datetime:
        """
        The latest moment, now or before, at which a weekday's clock in the exchange's zone read `at`: today's while it
        is a weekday and `at` has come, else the weekday's before. Exchange holidays are not modelled.
        """
        ...

    def next_settled_time(self) -> datetime:
        """
        When the next weekday session's daily bar becomes final, as last_settled_session counts it: today's while it is
        a weekday and that time is still ahead, else the next weekday's. Exchange holidays are not modelled.
        """
        ...

    def trading_phase(self) -> TradingPhase:
        """Where the exchange's trading day stands now. Exchange holidays and a delayed open or close are not modelled."""
        ...

    def until_odd_lot_session(self) -> timedelta:
        """
        How long from now until the intraday odd-lot session's first match, while continuous trading runs before it,
        and zero at any other time: never longer than from the continuous start to that match. Exchange holidays are not
        modelled.
        """
        ...
