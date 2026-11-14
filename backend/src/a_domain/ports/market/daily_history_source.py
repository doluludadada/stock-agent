from datetime import date
from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.types.enums import MarketType


class IDailyHistorySource(Protocol):
    """
    The exchanges' own reports of each date, which a personal site reads its daily history from without a login: every
    listed stock's official bar of one session, with its change from the session's reference price, each exchange's own
    index (the TAIEX, the TPEx Index) per session, and each exchange's ex-right references. A failed request raises.
    """

    async def session_bars(self, session: date) -> dict[str, Ohlcv]:
        """
        Every listed stock's bar of the session by stock id, stamped at the session's close, from both exchanges or
        from neither: a date without a session, or one that either exchange does not serve yet, has none at all. A stock
        that did not trade has no bar, and one whose exchange compared its close to no reference, as on an ex-dividend
        day, has no change.
        """
        ...

    async def index_bars(self, market: MarketType, first: date, last: date) -> list[Ohlcv]:
        """The market's own index per session from first to last, oldest first, each with its official change."""
        ...

    async def ex_right_references(self, market: MarketType, first: date, last: date) -> dict[tuple[str, date], float]:
        """
        The exchange's reference price of each of its stocks with a four-digit code on each of its ex-right or
        ex-dividend days from first to last, by stock id and day, in one request: the price its closing quotes compare
        to no reference that day. A range without such a day has none. An answer that is neither the exchange's table
        nor its word that the range has no such day raises: the range was not read.
        """
        ...
