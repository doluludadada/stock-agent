from dataclasses import replace
from datetime import date
from typing import Annotated

import numpy as np
from pydantic import Field, NonNegativeInt, PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.rules.trading.ranking import MonthlyRankingRule, RankedStock, Ranking, RankingHistory
from a_domain.types.enums import RankingExclusion, SecurityKind


@dataclass(frozen=True, kw_only=True)
class RankingStanding:
    """
    Where one stock stands in the monthly ranking at one decision session's close, as its page shows it. The score is
    not a forecast: it says how the stock's two factors rank among the stocks scored that day.
    """

    decided_on: date
    revenue_month: date
    """The first day of the month of revenue the ranking read."""

    universe: NonNegativeInt
    """The stocks that passed the ranking's universe at that close."""

    scored: NonNegativeInt
    """The universe's stocks with both factors, among which `place` counts."""

    top: PositiveInt
    """How many of the best scores the ranking holds: ranking.top."""

    place: PositiveInt | None
    """The stock's place among the scored stocks, 1 for the best combined rank. None when it has no score."""

    score: Annotated[float, Field(ge=0, le=100)] | None
    """
    The place as a percentile: 100 for the best combined rank of the day, 0 for the last. None when the stock has no
    score, or it is the only stock scored.
    """

    stock: RankedStock | None
    """Its two factors, each one's rank among the stocks that have it (0 to 1) and their sum. None when `place` is."""

    exclusion: RankingExclusion | None
    """Why the stock has no score. None when it has one."""

    @property
    def in_top(self) -> bool:
        """Whether the ranking holds the stock from the next session's open."""
        return self.place is not None and self.place <= self.top


@dataclass(frozen=True)
class RankingStandingRule:
    """
    One stock's standing in the monthly ranking at a decision session's close. The ranking is MonthlyRankingRule's own
    with no cut at its `top`, so a stock's place and factors are the ones the ranking page shows for the same day. A
    stock the ranking leaves out gets the first reason that applies: it has no bar in the held history, it is no
    stock, it did not trade that session, it enters once the liquidity floor is lifted, it enters once the price floor
    is lifted too, its revenue of one of the months the acceleration reads is not held, else the held history is
    shorter than the sessions the high needs. The floors are tested by ranking again without them, never by a second
    copy of the universe's conditions.
    """

    ranking_rule: MonthlyRankingRule

    def apply(self, history: RankingHistory, column: int, revenue_month: date, stock_id: str) -> RankingStanding:
        everyone = replace(self.ranking_rule, top=max(1, len(history.bars.stock_ids)))
        ranking = everyone.apply(history, column, revenue_month, {})
        places = {ranked.stock_id: place for place, ranked in enumerate(ranking.stocks, start=1)}
        place = places.get(stock_id)
        ahead = None if place is None or ranking.scored < 2 else (ranking.scored - place) / (ranking.scored - 1)

        return RankingStanding(
            decided_on=ranking.decided_on,
            revenue_month=ranking.revenue_month,
            universe=ranking.universe,
            scored=ranking.scored,
            top=self.ranking_rule.top,
            place=place,
            score=None if ahead is None else 100 * ahead,
            stock=None if place is None else ranking.stocks[place - 1],
            exclusion=None if place is not None else self._exclusion(everyone, history, column, revenue_month, stock_id),
        )

    def _exclusion(
        self, everyone: MonthlyRankingRule, history: RankingHistory, column: int, revenue_month: date, stock_id: str
    ) -> RankingExclusion:
        if stock_id not in history.bars.stock_ids:
            return RankingExclusion.NO_HISTORY

        row = history.bars.stock_ids.index(stock_id)

        if SecurityKind.of(stock_id) != SecurityKind.STOCK:
            return RankingExclusion.NOT_A_STOCK

        if np.isnan(history.bars.close[row, column]):
            return RankingExclusion.NOT_TRADED

        if self._ranks(replace(everyone, min_traded_value=0), history, column, revenue_month, stock_id):
            return RankingExclusion.ILLIQUID

        if self._ranks(replace(everyone, min_close=0, min_traded_value=0), history, column, revenue_month, stock_id):
            return RankingExclusion.PRICE_UNDER_FLOOR

        first = history.months[0] if history.months else revenue_month
        month = (revenue_month.year - first.year) * 12 + revenue_month.month - first.month
        read = history.revenue[row, max(0, month + 1 - everyone.long_months) : max(0, month + 1)]

        if len(read) < everyone.long_months or np.isnan(read).any():
            return RankingExclusion.NO_REVENUE_HISTORY

        return RankingExclusion.SHORT_PRICE_HISTORY

    def _ranks(self, rule: MonthlyRankingRule, history: RankingHistory, column: int, revenue_month: date, stock_id: str) -> bool:
        ranking: Ranking = rule.apply(history, column, revenue_month, {})
        return any(ranked.stock_id == stock_id for ranked in ranking.stocks)
