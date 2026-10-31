from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import icontract

from a_domain.model.market.ohlcv import Ohlcv


@icontract.invariant(lambda self: self.max_lag > timedelta(0))
@dataclass(frozen=True)
class DataFreshnessRule:
    """
    Market data older than `max_lag` must not drive a decision.

    Realtime quotes are compared as datetimes (minutes matter when they price an order).
    Daily history is compared as trading dates (days matter for technical analysis).
    """

    max_lag: timedelta

    def apply(self, observed_at: date, now: date) -> bool:
        return now - observed_at <= self.max_lag


@dataclass(frozen=True)
class RealtimeQuoteRule:
    """Why a stock's realtime quote cannot price an order at `now`, or None when it can."""

    freshness: DataFreshnessRule

    def apply(self, quote: Ohlcv | None, now: datetime) -> str | None:
        if quote is None:
            return "missing realtime bar"

        if self.freshness.apply(quote.ts, now):
            return None

        return f"stale realtime bar: {quote.ts.isoformat()}"


@icontract.invariant(lambda self: self.listed_stock_limit > 0)
@dataclass(frozen=True)
class MissingSessionRule:
    """
    The run error for daily histories that end before the last settled session, or None when every history has it.

    The price source has not published that session for those stocks yet. The error names at most
    `listed_stock_limit` of them.
    """

    listed_stock_limit: int

    def apply(self, last_sessions: Mapping[str, date], settled_session: date) -> str | None:
        behind = sorted(stock_id for stock_id, session in last_sessions.items() if session < settled_session)

        if not behind:
            return None

        shown = ", ".join(behind[: self.listed_stock_limit]) + (", ..." if len(behind) > self.listed_stock_limit else "")
        return (
            f"Daily history lacks the {settled_session} session for {len(behind)}/{len(last_sessions)} stocks ({shown}): "
            "the price source has not published it, so their analysis ends at an earlier close. "
            "An exchange holiday also reads as missing."
        )


@dataclass(frozen=True)
class MissedSessionsRule:
    """How many weekday sessions closed after `session`, up to and including `last_closed_session`."""

    def apply(self, session: date, last_closed_session: date) -> int:
        missed = 0
        day = session + timedelta(days=1)

        while day <= last_closed_session:
            if day.weekday() < 5:
                missed += 1
            day += timedelta(days=1)

        return missed


@icontract.invariant(lambda self: self.max_missed_sessions >= 0)
@dataclass(frozen=True)
class DailyCloseFreshnessRule:
    """
    A daily close is stale once more than `max_missed_sessions` weekday sessions have closed after its session.

    The shipped setting tolerates one missed session because the exchanges publish a day's close hours after 13:30:
    at 18:08 on 2026-10-30 TPEX already served 10-30 while TWSE still served 10-29.
    Exchange holidays are not modelled, so after a holiday longer than one weekday every close reads
    stale until the next close is published. That errs toward excluding a price, never toward using an old one.
    """

    max_missed_sessions: int

    def apply(self, session: date, last_closed_session: date) -> bool:
        return MissedSessionsRule().apply(session, last_closed_session) <= self.max_missed_sessions
