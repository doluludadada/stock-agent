from dataclasses import dataclass
from datetime import date, datetime, timedelta

import icontract


@icontract.invariant(lambda self: self.max_lag_minutes > 0)
@dataclass(frozen=True)
class DataFreshnessRule:
    """
    Data Freshness Evaluation Rule.

    Ensures that the ingested candlestick (OHLCV) timestamps align with the
    configured tolerance threshold to prevent stale data execution.
    """

    max_lag_minutes: int = 15
    """
    - max_lag_minutes (int): Maximum tolerated age of incoming data before flagging it as stale.
    """

    @property
    def max_lag(self) -> timedelta:
        """Converts the integer configuration into a comparable timedelta."""
        return timedelta(minutes=self.max_lag_minutes)

    def is_fresh(self, data_timestamp: datetime, current_time: datetime | None = None) -> bool:
        """
        Compares the data feed timestamp against current system time.

        Args:
            data_timestamp (datetime): The timestamp of the latest price quote.
            current_time (datetime | None): Optional mock current time (used in tests).

        Returns:
            bool: True if lag is within acceptable limits, False if stale.
        """
        if current_time is None:
            # Match timezone-awareness dynamically to prevent TypeError during comparison
            now = datetime.now(data_timestamp.tzinfo) if data_timestamp.tzinfo else datetime.now()
        else:
            now = current_time
            if now.tzinfo is None and data_timestamp.tzinfo is not None:
                now = now.replace(tzinfo=data_timestamp.tzinfo)

        return (now - data_timestamp) <= self.max_lag


@icontract.invariant(lambda self: self.max_missed_sessions >= 0)
@dataclass(frozen=True)
class DailyCloseFreshnessRule:
    """
    A daily close is stale once more than `max_missed_sessions` weekday sessions have closed after its session.

    One missed session is tolerated because the exchanges publish a day's close hours after 13:30:
    at 18:08 on 2026-10-30 TPEX already served 10-30 while TWSE still served 10-29.
    Exchange holidays are not modelled, so after a holiday longer than one weekday every close reads
    stale until the next close is published. That errs toward excluding a price, never toward using an old one.
    """

    max_missed_sessions: int = 1

    def missed_sessions(self, session: date, last_closed_session: date) -> int:
        """Weekdays d with session < d <= last_closed_session."""
        missed = 0
        day = session + timedelta(days=1)

        while day <= last_closed_session:
            if day.weekday() < 5:
                missed += 1
            day += timedelta(days=1)

        return missed

    def is_fresh(self, session: date, last_closed_session: date) -> bool:
        return self.missed_sessions(session, last_closed_session) <= self.max_missed_sessions
