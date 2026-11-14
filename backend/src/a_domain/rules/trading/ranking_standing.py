from collections.abc import Collection
from dataclasses import replace
from datetime import date
from typing import Annotated

import numpy as np
from pydantic import Field, NonNegativeInt, PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.rules.trading.ranking import MonthlyRankingRule, RankedStock, Ranking, RankingHistory, revenue_column
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


def bar_exclusion(history: RankingHistory, column: int, stock_id: str) -> RankingExclusion | None:
    """Why the stock has no bar the ranking could read at the session. None when it has one."""
    if stock_id not in history.bars.stock_ids:
        return RankingExclusion.NO_HISTORY

    if SecurityKind.of(stock_id) != SecurityKind.STOCK:
        return RankingExclusion.NOT_A_STOCK

    if np.isnan(history.bars.close[history.bars.stock_ids.index(stock_id), column]):
        return RankingExclusion.NOT_TRADED

    return None


def history_exclusion(everyone: MonthlyRankingRule, history: RankingHistory, revenue_month: date, stock_id: str) -> RankingExclusion:
    """Which history a stock that passes the universe without its floors still lacks for a score."""
    row = history.bars.stock_ids.index(stock_id)
    month = revenue_column(history, revenue_month)
    read = history.revenue[row, max(0, month + 1 - everyone.long_months) : max(0, month + 1)]

    if len(read) < everyone.long_months or np.isnan(read).any():
        return RankingExclusion.NO_REVENUE_HISTORY

    return RankingExclusion.SHORT_PRICE_HISTORY


def ranked_ids(rule: MonthlyRankingRule, history: RankingHistory, column: int, revenue_month: date) -> set[str]:
    ranking: Ranking = rule.apply(history, column, revenue_month, {})
    return {ranked.stock_id for ranked in ranking.stocks}


def exclusions(
    everyone: MonthlyRankingRule, history: RankingHistory, column: int, revenue_month: date, stock_ids: Collection[str]
) -> dict[str, RankingExclusion]:
    """
    Why the ranking leaves each of `stock_ids` out. Each floor is lifted by one more ranking for all of them, and only
    while a stock is still without a reason.
    """
    reasons = {stock_id: bar_exclusion(history, column, stock_id) for stock_id in stock_ids}
    lifted = (
        (RankingExclusion.ILLIQUID, replace(everyone, min_traded_value=0)),
        (RankingExclusion.PRICE_UNDER_FLOOR, replace(everyone, min_close=0, min_traded_value=0)),
    )

    for reason, without_floor in lifted:
        open_ids = [stock_id for stock_id, found in reasons.items() if found is None]
        ranked = ranked_ids(without_floor, history, column, revenue_month) if open_ids else set()
        reasons.update({stock_id: reason for stock_id in open_ids if stock_id in ranked})

    return {
        stock_id: found if found is not None else history_exclusion(everyone, history, revenue_month, stock_id)
        for stock_id, found in reasons.items()
    }


@dataclass(frozen=True)
class RankingStandingRule:
    """
    Each stock's standing in the monthly ranking at a decision session's close, by stock id. The ranking is
    MonthlyRankingRule's own with no cut at its `top`, made once for every stock asked, so a stock's place and factors
    are the ones the ranking page shows for the same day. A stock the ranking leaves out gets the first reason that
    applies: it has no bar in the held history, it is no stock, it did not trade that session, it enters once the
    liquidity floor is lifted, it enters once the price floor is lifted too, its revenue of one of the months the
    acceleration reads is not held, else the held history is shorter than the sessions the high needs. The floors are
    tested by ranking again without them, never by a second copy of the universe's conditions: at most two more
    rankings, however many stocks are asked.
    """

    ranking_rule: MonthlyRankingRule

    def apply(
        self, history: RankingHistory, column: int, revenue_month: date, stock_ids: Collection[str]
    ) -> dict[str, RankingStanding]:
        everyone = replace(self.ranking_rule, top=max(1, len(history.bars.stock_ids)))
        ranking = everyone.apply(history, column, revenue_month, {})
        places = {ranked.stock_id: place for place, ranked in enumerate(ranking.stocks, start=1)}
        unranked = [stock_id for stock_id in stock_ids if stock_id not in places]
        reasons = exclusions(everyone, history, column, revenue_month, unranked)
        standings: dict[str, RankingStanding] = {}

        for stock_id in stock_ids:
            place = places.get(stock_id)
            ahead = None if place is None or ranking.scored < 2 else (ranking.scored - place) / (ranking.scored - 1)
            standings[stock_id] = RankingStanding(
                decided_on=ranking.decided_on,
                revenue_month=ranking.revenue_month,
                universe=ranking.universe,
                scored=ranking.scored,
                top=self.ranking_rule.top,
                place=place,
                score=None if ahead is None else 100 * ahead,
                stock=None if place is None else ranking.stocks[place - 1],
                exclusion=reasons.get(stock_id),
            )

        return standings
