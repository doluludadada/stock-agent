from datetime import date, datetime

from pydantic import PositiveFloat
from pydantic.dataclasses import dataclass

from a_domain.types.enums import TradingPhase


@dataclass(frozen=True)
class QuoteRefresh:
    """What a page that shows the quote board's quotes is told about asking again."""

    changing: bool
    """
    The quotes may still change: a session trades, from the opening call auction to the close, or it closed today and
    its last quotes are not read yet. The board asks its source meanwhile, and a page marks its prices live.
    """

    seconds: PositiveFloat
    """How long a page waits before it asks again. The board asks its source no more often."""


@dataclass(frozen=True)
class QuoteRefreshRule:
    """
    Whether the quote board asks its source at this moment of the market's day, and when a page asks again. While a
    session trades the quotes change, so the board is asked every `refresh_seconds`. Once today's session closed, the
    board is asked until its source answered after that close, so that the quotes it holds are the session's last: one
    more request, made again while it fails. After that, and on a day without a session, nothing changes and a page
    looks every `recheck_seconds`, which sees the next session start.
    """

    refresh_seconds: PositiveFloat
    recheck_seconds: PositiveFloat

    def apply(self, phase: TradingPhase, today: date, last_closed: date, close: datetime, read_at: datetime | None) -> QuoteRefresh:
        """`last_closed` is the latest session that closed, `close` when today's closes, `read_at` when the source last answered."""
        if phase.in_session:
            return QuoteRefresh(changing=True, seconds=self.refresh_seconds)

        if last_closed == today and (read_at is None or read_at < close):
            return QuoteRefresh(changing=True, seconds=self.refresh_seconds)

        return QuoteRefresh(changing=False, seconds=self.recheck_seconds)
