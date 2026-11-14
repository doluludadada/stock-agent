from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from itertools import pairwise
from math import isclose
from typing import Annotated

from pydantic import Field
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.types.enums import MarketType


@dataclass(frozen=True)
class StockSearchRule:
    """
    The listed stocks that match what a user typed, best first: the exact code, then codes that start with it, then
    names that contain it, each group in listing order. Case and surrounding spaces do not matter.
    """

    limit: Annotated[int, Field(gt=0)]

    def apply(self, stocks: Sequence[Stock], query: str) -> list[Stock]:
        text = query.strip().casefold()

        if not text:
            return []

        exact = [stock for stock in stocks if stock.stock_id.casefold() == text]
        prefix = [stock for stock in stocks if stock.stock_id.casefold().startswith(text) and stock.stock_id.casefold() != text]
        named = [stock for stock in stocks if text in (stock.name or "").casefold() and not stock.stock_id.casefold().startswith(text)]

        return [*exact, *prefix, *named][: self.limit]


@dataclass(frozen=True)
class MostTradedRule:
    """The stocks with the most shares traded in the listing's latest session, most first."""

    limit: Annotated[int, Field(gt=0)]

    def apply(self, closes: Mapping[str, Ohlcv]) -> list[str]:
        ranked = sorted(closes.items(), key=lambda item: item[1].volume, reverse=True)
        return [stock_id for stock_id, _ in ranked[: self.limit]]


@dataclass(frozen=True)
class HistoryAdjustmentRule:
    """
    A stock's daily bars as its exchange listed them, oldest first, adjusted for the corporate actions between them, so
    that a split shows no gap that no trade made. A listed bar's change is from its session's reference price, so the
    reference is the close less the change; when it differs from the stock's close before, every earlier bar's prices
    and change are multiplied by reference / that close and its volume divided by it, so each bar's value traded stays
    as traded. The latest bar is as listed.

    Every action whose reference the exchange gives this way is adjusted, whatever its kind: the ratio alone cannot tell
    a cash dividend from a stock dividend or a split. Where the exchange compared the close to no reference (no change,
    or a change of 0 on a close unlike the one before, as TWSE writes X0.00 on an ex-dividend, ex-rights or
    capital-reduction day), the reference is the one `references` holds of the bar's stamp, its exchange's ex-right
    reference of that day. There is no factor rather than a wrong one where there is none, so such a day stays as listed, across a
    session the archive missed, and, on an exchange whose change after a session the stock did not trade is from a moved
    reference (MarketType.changes_from_a_moved_reference), across such a session. `index` is the exchange index's close
    of each session the archive holds the market's closes of; an index close whose own change does not lead back to the
    one before it shows a session missing between them. A split's suspension is such a session too, so a split is
    adjusted on TWSE only.
    """

    def apply(
        self, bars: Sequence[Ohlcv], index: Sequence[Ohlcv], market: MarketType, references: Mapping[datetime, float]
    ) -> list[Ohlcv]:
        sessions = self._sessions(index)
        adjusted, factor = list(bars[-1:]), 1.0

        for earlier, later in reversed(list(pairwise(bars))):
            if self._comparable(sessions.get(earlier.ts), sessions.get(later.ts), market):
                factor *= self._factor(earlier, later, references.get(later.ts))

            adjusted.append(earlier if factor == 1 else self._scaled(earlier, factor))

        return adjusted[::-1]

    def _sessions(self, index: Sequence[Ohlcv]) -> dict[datetime, tuple[int, int]]:
        """
        Each session's run of sessions with none missing between them, numbered from the oldest, and its place among
        the sessions.
        """
        sessions = {bar.ts: (0, 0) for bar in index[:1]}

        for place, (earlier, later) in enumerate(pairwise(index), start=1):
            reference = self._reference(earlier.close, later, None)
            follows = reference is not None and isclose(reference, earlier.close)
            sessions[later.ts] = (sessions[earlier.ts][0] + (0 if follows else 1), place)

        return sessions

    def _comparable(self, earlier: tuple[int, int] | None, later: tuple[int, int] | None, market: MarketType) -> bool:
        """Whether the later bar's change can be read against the earlier bar's close."""
        if earlier is None or later is None or earlier[0] != later[0]:
            return False

        return later[1] - earlier[1] == 1 or not market.changes_from_a_moved_reference

    def _factor(self, earlier: Ohlcv, later: Ohlcv, listed: float | None) -> float:
        reference = self._reference(earlier.close, later, listed)

        if reference is None or isclose(reference, earlier.close):
            return 1.0

        return reference / earlier.close

    def _reference(self, previous_close: float, bar: Ohlcv, listed: float | None) -> float | None:
        """
        The price the exchange compared the bar's close to; where its change compares to none, the ex-right reference
        `listed` of its session, or None.
        """
        if bar.change is None or (bar.change == 0 and not isclose(bar.close, previous_close)):
            return listed

        return bar.close - bar.change

    def _scaled(self, bar: Ohlcv, factor: float) -> Ohlcv:
        return replace(
            bar,
            open=bar.open * factor,
            high=bar.high * factor,
            low=bar.low * factor,
            close=bar.close * factor,
            volume=round(bar.volume / factor),
            change=None if bar.change is None else bar.change * factor,
        )
