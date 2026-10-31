from dataclasses import dataclass
from datetime import date, timedelta

import icontract


@icontract.invariant(lambda self: self.max_lag > timedelta(0))
@dataclass(frozen=True)
class DataFreshnessRule:
    """
    Market data older than `max_lag` must not drive a decision.

    Realtime quotes are compared as datetimes (minutes matter when they price an order).
    Daily history is compared as trading dates (days matter for technical analysis).
    """

    max_lag: timedelta

    def age(self, observed_at: date, now: date) -> timedelta:
        return now - observed_at

    def is_fresh(self, observed_at: date, now: date) -> bool:
        return self.age(observed_at, now) <= self.max_lag


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
