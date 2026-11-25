from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from functools import reduce
from typing import Annotated

import numpy as np
from pydantic import ConfigDict, Field, FiniteFloat, NonNegativeFloat, NonNegativeInt, PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.trading.ranking_formula import (
    NearnessToHigh,
    PriceMomentum,
    RankingFactor,
    RankingFormula,
    RevenueAcceleration,
    RevenueYoy,
)
from a_domain.rules.technical.matrix import DailyBarMatrix, DailyBarMatrixRule, last_closes
from a_domain.types.enums import SecurityKind
from a_domain.types.errors import RankingUnavailable
from a_domain.types.values import Flags, Floats, Fraction, NonEmptyText, ProperFraction, month_index, month_start

type DayOfMonth = Annotated[int, Field(ge=1, le=28)]


@dataclass(frozen=True, config=ConfigDict(arbitrary_types_allowed=True))
class ListedHistory:
    """
    Every stock's daily bars as its exchange listed them, delisted stocks too, one row per stock and one column per
    session: a past close is the price it traded at, never adjusted by a later action. With each bar's change from the
    session's reference price, and the ex-right reference its exchange listed for its session; NaN where a bar has none.
    """

    bars: DailyBarMatrix
    change: Floats
    ex_right_reference: Floats


@dataclass(frozen=True)
class ListedHistoryRule:
    """
    The listed history of the stocks of `history` with their ex-right references, keyed as the bars are stamped. A
    reference of a session the stock has no bar of is left out.
    """

    def apply(
        self,
        history: Mapping[str, Sequence[Ohlcv]],
        references: Mapping[str, Mapping[datetime, float]],
        trading_date: Callable[[datetime], date],
    ) -> ListedHistory:
        bars = DailyBarMatrixRule().apply(history, trading_date)
        sessions = {session: column for column, session in enumerate(bars.sessions)}
        rows = {stock_id: row for row, stock_id in enumerate(bars.stock_ids)}
        columns = {stamp: sessions[trading_date(stamp)] for stamp in {bar.ts for listed in history.values() for bar in listed}}
        change = np.full(bars.close.shape, np.nan)

        for stock_id, row in rows.items():
            change[row, [columns[bar.ts] for bar in history[stock_id]]] = [
                np.nan if bar.change is None else bar.change for bar in history[stock_id]
            ]

        return ListedHistory(bars=bars, change=change, ex_right_reference=ex_right_matrix(references, rows, columns, bars.close))


def ex_right_matrix(
    references: Mapping[str, Mapping[datetime, float]], rows: Mapping[str, int], columns: Mapping[datetime, int], close: Floats
) -> Floats:
    """
    Each reference in its stock's row and its stamp's column, in the shape of `close`, NaN everywhere else: a reference
    of a stamp no bar has, or of a session its stock has no bar of, is left out.
    """
    placed = np.full(close.shape, np.nan)

    for stock_id in references.keys() & rows.keys():
        listed = [(columns[stamp], price) for stamp, price in references[stock_id].items() if stamp in columns]
        placed[rows[stock_id], [column for column, _ in listed]] = [price for _, price in listed]

    return np.where(np.isnan(close), np.nan, placed)


@dataclass(frozen=True, config=ConfigDict(arbitrary_types_allowed=True))
class RankingHistory:
    """
    What the ranking reads, each stock in its row of `bars`: its bars as listed; each bar's total return since the
    stock's bar before (RankingHistoryRule), 0 where it has no bar; the total-return level, those returns compounded
    from the first session, 1 before the stock's first bar; and its revenue of each of `months`, NaN where none is held.
    """

    bars: DailyBarMatrix
    returns: Floats
    level: Floats
    revenue: Floats
    months: tuple[date, ...]
    """The first day of each revenue column's month, consecutive months, oldest first."""


@dataclass(frozen=True)
class RankingHistoryRule:
    """
    The ranking's history from the listed one and the revenue the archive holds. A bar's total return is its change
    over the price the exchange compared its close to (close - change) where it gives a change, else its close over
    its exchange's ex-right reference of the day, less 1; without either, its move from the stock's close before, but 0 when that
    move is beyond `daily_limit`, which no trade can make, so it is an action the exchange named no reference of.
    """

    daily_limit: ProperFraction

    def apply(self, listed: ListedHistory, revenues: Mapping[tuple[str, int, int], float | None]) -> RankingHistory:
        close, change, ex_right = listed.bars.close, listed.change, listed.ex_right_reference
        previous = np.roll(last_closes(close), 1, axis=1)
        previous[:, 0] = np.nan

        with np.errstate(all="ignore"):
            moved = close / previous - 1
            returns = np.select(
                [~np.isnan(change) & (close - change > 0), ex_right > 0, ~np.isnan(moved)],
                [change / (close - change), close / ex_right - 1, np.where(np.abs(moved) > self.daily_limit, 0.0, moved)],
                default=0.0,
            )

        revenue, months = revenue_matrix(listed.bars.stock_ids, revenues)
        return RankingHistory(bars=listed.bars, returns=returns, level=np.cumprod(1 + returns, axis=1), revenue=revenue, months=months)


def revenue_matrix(stock_ids: Sequence[str], revenues: Mapping[tuple[str, int, int], float | None]) -> tuple[Floats, tuple[date, ...]]:
    """
    Each stock's revenue of each month from the first held to the last, NaN where none is held. `revenues` holds each
    company's revenue of each month by stock id, year and month, None where its figure was left blank.
    """
    rows = {stock_id: row for row, stock_id in enumerate(stock_ids)}
    held = [
        (rows[stock_id], month_index(year, month), amount) for (stock_id, year, month), amount in revenues.items() if stock_id in rows
    ]
    months = range(min((month for _, month, _ in held), default=0), max((month for _, month, _ in held), default=-1) + 1)
    matrix = np.full((len(rows), len(months)), np.nan)

    for row, month, amount in held:
        matrix[row, month - months.start] = np.nan if amount is None else amount

    return matrix, tuple(month_start(month) for month in months)


@dataclass(frozen=True)
class DecisionSessionsRule:
    """
    Each month's decision session among `sessions`, oldest first, with the month of revenue it reads: the first session
    whose day of the month is `decision_day` or later. It decides at that session's close and reads the newest month
    whose revenue was due before it, by the `deadline_day` of the month after: the month before the session's when the
    session falls after that day, else the month before that.
    """

    decision_day: DayOfMonth
    deadline_day: DayOfMonth

    def apply(self, sessions: Sequence[date]) -> list[tuple[int, date]]:
        decisions: dict[tuple[int, int], tuple[int, date]] = {}

        for column, session in enumerate(sessions):
            if session.day < self.decision_day or (session.year, session.month) in decisions:
                continue

            month = month_index(session.year, session.month) - (1 if session.day > self.deadline_day else 2)
            decisions[(session.year, session.month)] = (column, month_start(month))

        return list(decisions.values())


def latest_decision(decision_rule: DecisionSessionsRule, sessions: Sequence[date]) -> tuple[int, date]:
    """The latest decision session among `sessions`, as its column, and the month of revenue it reads. RankingUnavailable if none."""
    decisions = decision_rule.apply(sessions)

    if not decisions:
        raise RankingUnavailable(
            f"No ranking can be made yet: the daily history holds {sessions[0]} to {sessions[-1]}, and no decision session."
        )

    return decisions[-1]


@dataclass(frozen=True, kw_only=True)
class RankedFactor:
    """One factor of a ranked stock: its value, and its place among the universe's stocks that have it, 0 lowest to 1."""

    value: FiniteFloat
    rank: Fraction


@dataclass(
    frozen=True, kw_only=True, config=ConfigDict(json_schema_serialization_defaults_required=True, use_attribute_docstrings=True)
)
class RankedStock:
    """One stock of a ranking: each factor of the ranking's formula, in the formula's order, and its score."""

    stock_id: NonEmptyText
    stock_name: str | None = None
    factors: list[RankedFactor]
    score: NonNegativeFloat
    """The sum of the factors' ranks."""


@dataclass(frozen=True, kw_only=True, config=ConfigDict(use_attribute_docstrings=True))
class Ranking:
    """The monthly ranking at one decision session's close: the stocks to hold from the next session's open."""

    formula: RankingFormula
    """The formula that made it."""

    decided_on: date
    revenue_month: date
    """The first day of the month of revenue it read."""

    universe: NonNegativeInt
    """The stocks that passed the universe at the close: traded, liquid enough and priced at least min_close."""

    scored: NonNegativeInt
    """The universe's stocks with every factor, each of which has a score."""

    holds_cash: bool = False
    """The formula's market filter is on: it holds no stock until the next decision, though the factors are measured."""

    stocks: list[RankedStock]
    """The `top` best scores, best first; equal scores in stock id order. None while it holds cash."""

    @property
    def decides(self) -> bool:
        """
        Whether it says what to hold: its stocks, or cash while the market filter is on. Any other ranking of no stock,
        a month whose revenue the site does not hold, is no instruction: nothing is sold for it and no follow takes it.
        """
        return bool(self.stocks) or self.holds_cash


def in_universe(
    bars: DailyBarMatrix,
    column: int,
    min_close: NonNegativeFloat,
    min_traded_value: NonNegativeFloat,
    traded_value_sessions: PositiveInt,
) -> Flags:
    if column + 1 < traded_value_sessions:
        return np.zeros(len(bars.stock_ids), dtype=np.bool_)

    window = slice(column + 1 - traded_value_sessions, column + 1)
    traded_value = np.nan_to_num(bars.close[:, window] * bars.volume[:, window]).mean(axis=1)
    stock = np.array([SecurityKind.of(stock_id) == SecurityKind.STOCK for stock_id in bars.stock_ids])

    with np.errstate(invalid="ignore"):
        return stock & (bars.close[:, column] >= min_close) & (traded_value >= min_traded_value)


def revenue_column(history: RankingHistory, revenue_month: date) -> int:
    """The column of `revenue_month` in the history's revenue, which may lie before its first month or after its last."""
    first = history.months[0] if history.months else revenue_month
    return month_index(revenue_month.year, revenue_month.month) - month_index(first.year, first.month)


def revenue_acceleration(revenue: Floats, month: int, short_months: PositiveInt, long_months: PositiveInt) -> Floats:
    """
    Each row's mean revenue of the `short_months` months to column `month` over its mean of the `long_months` months
    to it. NaN where a month of the window is not held or the ratio is not finite. The monthly ranking and a stock's
    revenue trend both read it here.
    """
    if month + 1 < long_months or month >= revenue.shape[1]:
        return np.full(revenue.shape[0], np.nan)

    short = np.sum(revenue[:, month + 1 - short_months : month + 1], axis=1) / short_months
    long = np.sum(revenue[:, month + 1 - long_months : month + 1], axis=1) / long_months

    with np.errstate(all="ignore"):
        acceleration = short / long

    return np.where(np.isfinite(acceleration), acceleration, np.nan)


def revenue_yoy(revenue: Floats, month: int, months: PositiveInt) -> Floats:
    """
    Each row's revenue of the `months` months to column `month` over its revenue of the same months a year before,
    less 1. NaN where a month of either window is not held or the year before's revenue is not above 0.
    """
    first = month + 1 - months
    year_before = first - 12

    if year_before < 0 or month >= revenue.shape[1]:
        return np.full(revenue.shape[0], np.nan)

    latest = revenue[:, first : first + months].sum(axis=1)
    before = revenue[:, year_before : year_before + months].sum(axis=1)

    with np.errstate(all="ignore"):
        growth = np.where(before > 0, latest / before - 1, np.nan)

    return np.where(np.isfinite(growth), growth, np.nan)


def nearness_to_high(history: RankingHistory, column: int, high_sessions: PositiveInt) -> Floats:
    first = column + 1 - high_sessions

    if first < 0:
        return np.full(len(history.bars.stock_ids), np.nan)

    listed = ~np.isnan(history.bars.close[:, : first + 1]).all(axis=1)
    return np.where(listed, history.level[:, column] / history.level[:, first : column + 1].max(axis=1), np.nan)


def price_momentum(history: RankingHistory, column: int, sessions: PositiveInt, skip_sessions: NonNegativeInt) -> Floats:
    """
    Each row's total-return level `skip_sessions` sessions before column `column` over its level `sessions` sessions
    before it, less 1. NaN while the stock's first bar is later than the older of the two.
    """
    first = column - sessions

    if first < 0:
        return np.full(len(history.bars.stock_ids), np.nan)

    listed = ~np.isnan(history.bars.close[:, : first + 1]).all(axis=1)
    return np.where(listed, history.level[:, column - skip_sessions] / history.level[:, first] - 1, np.nan)


def factor_values(factor: RankingFactor, history: RankingHistory, column: int, month: int) -> Floats:
    """Every stock's value of one factor at the session of `column`, reading the revenue to column `month`. NaN where it has none."""
    match factor:
        case RevenueAcceleration():
            return revenue_acceleration(history.revenue, month, factor.short_months, factor.long_months)
        case RevenueYoy():
            return revenue_yoy(history.revenue, month, factor.months)
        case NearnessToHigh():
            return nearness_to_high(history, column, factor.high_sessions)
        case PriceMomentum():
            return price_momentum(history, column, factor.sessions, factor.skip_sessions)


def measured_factors(
    formula: RankingFormula, history: RankingHistory, column: int, revenue_month: date
) -> tuple[Flags, list[Floats], list[Floats]]:
    """
    The formula's universe at the session, and each of its factors in order: every stock's value, NaN outside the
    universe, and its rank among the universe's stocks that have the factor (`ranks`).
    """
    universe = in_universe(history.bars, column, formula.min_close, formula.min_traded_value, formula.traded_value_sessions)
    month = revenue_column(history, revenue_month)
    values = [np.where(universe, factor_values(factor, history, column, month), np.nan) for factor in formula.factors]

    return universe, values, [ranks(factor) for factor in values]


def holds_cash(formula: RankingFormula, benchmark_id: NonEmptyText, history: RankingHistory, column: int) -> bool:
    """
    Whether the formula's market filter is on at the session: the benchmark's total-return level at its close is under
    the level's average of the last cash_under_average_sessions sessions, that close among them. A formula without the
    filter never holds cash, and neither does one whose average the history is still too short for. RankingUnavailable
    when the history holds no bar of the benchmark, since the filter cannot be read.
    """
    sessions = formula.cash_under_average_sessions

    if sessions is None or column + 1 < sessions:
        return False

    if benchmark_id not in history.bars.stock_ids:
        raise RankingUnavailable(
            f"The formula {formula.name} holds cash while {benchmark_id} is under its {sessions}-session average, and the "
            f"daily history holds no bar of {benchmark_id}."
        )

    level = history.level[history.bars.stock_ids.index(benchmark_id), column + 1 - sessions : column + 1]

    return bool(level[-1] < level.mean())


@dataclass(frozen=True)
class MonthlyRankingRule:
    """
    The ranking a formula makes at a decision session's close. The universe is every stock (no ETF) that traded that
    session, closed at the formula's `min_close` or more, and traded `min_traded_value` a session on average over the
    last `traded_value_sessions` sessions, a session without a trade counting 0. Each factor of the formula is measured
    for the universe's stocks (factor_values) and ranked among those that have it (`ranks`); a stock's score is the sum
    of its ranks, none while it lacks a factor, and the `top` best scores are the ranking. While the formula's market
    filter is on (holds_cash, against `benchmark_id`), the ranking holds no stock; its universe and its scored stocks
    are counted all the same. Prices are as listed, so a past close is the price it traded at.
    """

    formula: RankingFormula
    benchmark_id: NonEmptyText

    def apply(self, history: RankingHistory, column: int, revenue_month: date, names: Mapping[str, str | None]) -> Ranking:
        universe, values, placed = measured_factors(self.formula, history, column, revenue_month)
        score = reduce(np.add, placed)
        scored = np.flatnonzero(~np.isnan(score))
        cash = holds_cash(self.formula, self.benchmark_id, history, column)
        best = [] if cash else scored[np.argsort(-score[scored], kind="stable")][: self.formula.top].tolist()
        stocks = [
            RankedStock(
                stock_id=history.bars.stock_ids[row],
                stock_name=names.get(history.bars.stock_ids[row]),
                factors=[
                    RankedFactor(value=float(value[row]), rank=float(rank[row])) for value, rank in zip(values, placed, strict=True)
                ],
                score=float(score[row]),
            )
            for row in best
        ]

        return Ranking(
            formula=self.formula,
            decided_on=history.bars.sessions[column],
            revenue_month=revenue_month,
            universe=int(universe.sum()),
            scored=len(scored),
            holds_cash=cash,
            stocks=stocks,
        )


def ranks(values: Floats) -> Floats:
    """
    Each value's place among the values that are not NaN, from 0 for the lowest to 1 for the highest; equal values
    share the mean of their places. NaN stays NaN, and so does every value while fewer than two are not NaN.
    """
    held = np.flatnonzero(~np.isnan(values))
    places = np.full(len(values), np.nan)

    if len(held) < 2:
        return places

    order = held[np.argsort(values[held], kind="stable")]
    ordered = values[order]
    starts = np.flatnonzero(np.r_[True, ordered[1:] != ordered[:-1]])
    ends = np.r_[starts[1:], len(order)]
    places[order] = np.repeat((starts + ends - 1) / 2, ends - starts) / (len(held) - 1)

    return places
