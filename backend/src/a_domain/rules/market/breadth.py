from collections.abc import Mapping
from datetime import datetime
from typing import Annotated

from pydantic import Field
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv


@dataclass(frozen=True)
class Breadth:
    """
    How many stocks rose, fell and closed unchanged in one session, and their average change in percent, each stock
    weighing the same.
    """

    advancers: Annotated[int, Field(ge=0)]
    decliners: Annotated[int, Field(ge=0)]
    unchanged: Annotated[int, Field(ge=0)]
    average_change_percent: float


@dataclass(frozen=True)
class MarketBreadth:
    session_close: datetime
    """The listing's latest session, stamped at its close like its bars."""

    market: Breadth
    """Every stock with an official close and change in that session."""

    industries: dict[str, Breadth]
    """The same stocks per industry. A stock without an industry counts in `market` only."""


@dataclass(frozen=True)
class MarketBreadthRule:
    """
    The breadth of the listing's latest session. A stock's change is the exchange's own, from its reference price. A
    close of an earlier session, from a listing not updated yet, and a close without a change are left out.
    """

    def apply(self, closes: Mapping[str, Ohlcv], industries: Mapping[str, str]) -> MarketBreadth | None:
        reported = [
            (stock_id, bar.ts, bar.change / (bar.close - bar.change) * 100)
            for stock_id, bar in closes.items()
            if bar.change is not None
        ]

        if not reported:
            return None

        session_close = max(ts for _, ts, _ in reported)
        changes = {stock_id: change for stock_id, ts, change in reported if ts == session_close}
        by_industry: dict[str, list[float]] = {}

        for stock_id, change in changes.items():
            if industry := industries.get(stock_id):
                by_industry.setdefault(industry, []).append(change)

        return MarketBreadth(
            session_close=session_close,
            market=self._breadth(list(changes.values())),
            industries={industry: self._breadth(group) for industry, group in by_industry.items()},
        )

    def _breadth(self, changes: list[float]) -> Breadth:
        return Breadth(
            advancers=sum(change > 0 for change in changes),
            decliners=sum(change < 0 for change in changes),
            unchanged=sum(change == 0 for change in changes),
            average_change_percent=sum(changes) / len(changes),
        )
