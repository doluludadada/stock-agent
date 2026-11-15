from collections.abc import Collection
from dataclasses import replace
from datetime import date
from typing import Annotated

import numpy as np
from pydantic import Field, NonNegativeInt, PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.trading.ranking_formula import RankingFormula
from a_domain.rules.trading.ranking import MonthlyRankingRule, RankedStock, RankingHistory, holds_cash, measured_factors
from a_domain.types.enums import RankingExclusion, SecurityKind


@dataclass(frozen=True, kw_only=True)
class RankingStanding:
    """
    Where one stock stands in the monthly ranking at one decision session's close, as its page shows it. The score is
    not a forecast: it says how the stock's factors rank among the stocks scored that day.
    """

    formula: RankingFormula
    """The formula that ranked it; its `top` is how many of the best scores the ranking holds."""

    decided_on: date
    revenue_month: date
    """The first day of the month of revenue the ranking read."""

    universe: NonNegativeInt
    """The stocks that passed the ranking's universe at that close."""

    scored: NonNegativeInt
    """The universe's stocks with every factor, among which `place` counts."""

    holds_cash: bool
    """The formula's market filter is on: the ranking holds no stock now, and the score is measured all the same."""

    place: PositiveInt | None
    """The stock's place among the scored stocks, 1 for the best combined rank. None when it has no score."""

    score: Annotated[float, Field(ge=0, le=100)] | None
    """
    The place as a percentile: 100 for the best combined rank of the day, 0 for the last. None when the stock has no
    score, or it is the only stock scored.
    """

    stock: RankedStock | None
    """Each factor of the formula with its rank among the stocks that have it (0 to 1), and their sum. None when `place` is."""

    exclusion: RankingExclusion | None
    """Why the stock has no score. None when it has one."""

    @property
    def in_top(self) -> bool:
        """Whether the ranking holds the stock from the next session's open."""
        return self.place is not None and self.place <= self.formula.top and not self.holds_cash


def bar_exclusion(history: RankingHistory, column: int, stock_id: str) -> RankingExclusion | None:
    """Why the stock has no bar the ranking could read at the session. None when it has one."""
    if stock_id not in history.bars.stock_ids:
        return RankingExclusion.NO_HISTORY

    if SecurityKind.of(stock_id) != SecurityKind.STOCK:
        return RankingExclusion.NOT_A_STOCK

    if np.isnan(history.bars.close[history.bars.stock_ids.index(stock_id), column]):
        return RankingExclusion.NOT_TRADED

    return None


def history_exclusions(
    without_floors: RankingFormula, history: RankingHistory, column: int, revenue_month: date, stock_ids: Collection[str]
) -> dict[str, RankingExclusion]:
    """
    Which history each stock that passes the universe without its floors still lacks for a score: that of the first
    factor of the formula that gives it no rank (RankingFactorKind.missing_history).
    """
    _, _, placed = measured_factors(without_floors, history, column, revenue_month)
    reasons: dict[str, RankingExclusion] = {}

    for stock_id in stock_ids:
        row = history.bars.stock_ids.index(stock_id)
        unranked = [factor for factor, rank in zip(without_floors.factors, placed, strict=True) if np.isnan(rank[row])]
        reasons[stock_id] = (unranked or without_floors.factors)[0].kind.missing_history

    return reasons


def ranked_ids(rule: MonthlyRankingRule, history: RankingHistory, column: int, revenue_month: date) -> set[str]:
    return {ranked.stock_id for ranked in rule.apply(history, column, revenue_month, {}).stocks}


def exclusions(
    everyone: MonthlyRankingRule, history: RankingHistory, column: int, revenue_month: date, stock_ids: Collection[str]
) -> dict[str, RankingExclusion]:
    """
    Why the ranking leaves each of `stock_ids` out. Each floor is lifted by one more ranking for all of them, and only
    while a stock is still without a reason.
    """
    reasons = {stock_id: bar_exclusion(history, column, stock_id) for stock_id in stock_ids}
    liquid = replace(everyone.formula, min_traded_value=0)
    without_floors = replace(liquid, min_close=0)
    lifted = ((RankingExclusion.ILLIQUID, liquid), (RankingExclusion.PRICE_UNDER_FLOOR, without_floors))

    for reason, formula in lifted:
        open_ids = [stock_id for stock_id, found in reasons.items() if found is None]
        ranked = ranked_ids(replace(everyone, formula=formula), history, column, revenue_month) if open_ids else set()
        reasons.update({stock_id: reason for stock_id in open_ids if stock_id in ranked})

    unscored = [stock_id for stock_id, found in reasons.items() if found is None]
    lacking = history_exclusions(without_floors, history, column, revenue_month, unscored) if unscored else {}

    return {stock_id: found if found is not None else lacking[stock_id] for stock_id, found in reasons.items()}


@dataclass(frozen=True)
class RankingStandingRule:
    """
    Each stock's standing in the monthly ranking at a decision session's close, by stock id. The ranking is
    MonthlyRankingRule's own with no cut at its formula's `top` and whatever its market filter says, made once for every
    stock asked, so a stock's place and factors are the ones the ranking page shows for the same day, and a formula
    that holds cash still scores. A stock the ranking leaves out gets the first reason that applies: it has no bar in
    the held history, it is no stock, it did not trade that session, it enters once the liquidity floor is lifted, it
    enters once the price floor is lifted too, else the history one of the formula's factors reads is not held. The
    floors are tested by ranking again without them, never by a second copy of the universe's conditions: at most two
    more rankings, however many stocks are asked.
    """

    ranking_rule: MonthlyRankingRule

    def apply(
        self, history: RankingHistory, column: int, revenue_month: date, stock_ids: Collection[str]
    ) -> dict[str, RankingStanding]:
        formula = self.ranking_rule.formula
        uncut = replace(formula, top=max(1, len(history.bars.stock_ids)), cash_under_average_sessions=None)
        everyone = replace(self.ranking_rule, formula=uncut)
        ranking = everyone.apply(history, column, revenue_month, {})
        places = {ranked.stock_id: place for place, ranked in enumerate(ranking.stocks, start=1)}
        unranked = [stock_id for stock_id in stock_ids if stock_id not in places]
        reasons = exclusions(everyone, history, column, revenue_month, unranked)
        cash = holds_cash(formula, self.ranking_rule.benchmark_id, history, column)
        standings: dict[str, RankingStanding] = {}

        for stock_id in stock_ids:
            place = places.get(stock_id)
            ahead = None if place is None or ranking.scored < 2 else (ranking.scored - place) / (ranking.scored - 1)
            standings[stock_id] = RankingStanding(
                formula=formula,
                decided_on=ranking.decided_on,
                revenue_month=ranking.revenue_month,
                universe=ranking.universe,
                scored=ranking.scored,
                holds_cash=cash,
                place=place,
                score=None if ahead is None else 100 * ahead,
                stock=None if place is None else ranking.stocks[place - 1],
                exclusion=reasons.get(stock_id),
            )

        return standings
