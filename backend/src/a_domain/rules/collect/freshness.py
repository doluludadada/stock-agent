from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Annotated

from pydantic import Field, NonNegativeInt, PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.types.enums import MarketType


@dataclass(frozen=True)
class DataFreshnessRule:
    """
    Market data older than `max_lag` must not drive a decision.

    Realtime quotes are compared as datetimes (minutes matter when they price an order).
    Daily history is compared as trading dates (days matter for technical analysis).
    """

    max_lag: Annotated[timedelta, Field(gt=timedelta(0))]

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


@dataclass(frozen=True)
class MissingSessionRule:
    """
    The run error for daily histories that end before the last settled session, or None when none is missing.

    An exchange publishes a session for all its stocks at once, so a session is missing only when no stock of that
    exchange has it. A stock without it while others of its exchange have it did not trade that session: its history
    is complete, so that is no error. The error names at most `listed_stock_limit` of the stocks.
    """

    listed_stock_limit: PositiveInt

    def apply(self, last_sessions: Mapping[str, tuple[MarketType, date]], settled_session: date) -> str | None:
        published = {market for market, session in last_sessions.values() if session >= settled_session}
        behind = sorted(stock_id for stock_id, (market, _) in last_sessions.items() if market not in published)

        if not behind:
            return None

        markets = " or ".join(sorted({last_sessions[stock_id][0].name for stock_id in behind}))
        shown = ", ".join(behind[: self.listed_stock_limit]) + (", ..." if len(behind) > self.listed_stock_limit else "")
        return (
            f"Daily history lacks the {settled_session} session for {len(behind)}/{len(last_sessions)} stocks ({shown}): "
            f"no {markets} stock has it, so {markets} has not published it yet, it was an exchange holiday, "
            "or none of these stocks traded. Their analysis ends at an earlier close."
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


@dataclass(frozen=True)
class DailyCloseFreshnessRule:
    """
    A daily close is stale once more than `max_missed_sessions` weekday sessions have closed after its session.

    The shipped setting tolerates one missed session because the exchanges publish a day's close hours after 13:30:
    at 18:08 on 2026-10-30 TPEX already served 10-30 while TWSE still served 10-29.
    Exchange holidays are not modelled, so after a holiday longer than one weekday every close reads
    stale until the next close is published. That errs toward excluding a price, never toward using an old one.
    """

    max_missed_sessions: NonNegativeInt

    def apply(self, session: date, last_closed_session: date) -> bool:
        return MissedSessionsRule().apply(session, last_closed_session) <= self.max_missed_sessions
