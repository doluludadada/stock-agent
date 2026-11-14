from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Annotated, Self

import numpy as np
from pydantic import ConfigDict, Field, FiniteFloat, NonNegativeFloat, NonNegativeInt, PositiveInt, model_validator
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.rules.technical.matrix import DailyBarMatrix, DailyBarMatrixRule, Flags, Floats, last_closes
from a_domain.types.enums import SecurityKind
from a_domain.types.values import Fraction, NonEmptyText, ProperFraction, month_index, month_start

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


@dataclass(
    frozen=True, kw_only=True, config=ConfigDict(json_schema_serialization_defaults_required=True, use_attribute_docstrings=True)
)
class RankedStock:
    """One stock of a ranking: its two factors, the rank of each among the universe's stocks that have it, and its score."""

    stock_id: NonEmptyText
    stock_name: str | None = None
    revenue_acceleration: FiniteFloat
    """The mean revenue of the latest short months over the mean of the latest long months, up to the month read."""

    nearness_to_high: FiniteFloat
    """
    The total-return level at the decision's close over its highest of the last high_sessions sessions: 1 at a high. A
    stock listed after the first of those sessions has none.
    """

    acceleration_rank: Fraction
    nearness_rank: Fraction
    """Each factor's place among the universe's stocks that have it, from 0 for the lowest to 1 for the highest."""

    score: Annotated[float, Field(ge=0, le=2)]
    """The sum of the two ranks."""


@dataclass(frozen=True, kw_only=True, config=ConfigDict(use_attribute_docstrings=True))
class Ranking:
    """The monthly ranking at one decision session's close: the stocks to hold from the next session's open."""

    decided_on: date
    revenue_month: date
    """The first day of the month of revenue it read."""

    universe: NonNegativeInt
    """The stocks that passed the universe at the close: traded, liquid enough and priced at least min_close."""

    scored: NonNegativeInt
    """The universe's stocks with both factors, each of which has a score."""

    stocks: list[RankedStock]
    """The `top` best scores, best first; equal scores in stock id order."""


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


def nearness_to_high(history: RankingHistory, column: int, high_sessions: PositiveInt) -> Floats:
    first = column + 1 - high_sessions

    if first < 0:
        return np.full(len(history.bars.stock_ids), np.nan)

    listed = ~np.isnan(history.bars.close[:, : first + 1]).all(axis=1)
    return np.where(listed, history.level[:, column] / history.level[:, first : column + 1].max(axis=1), np.nan)


@dataclass(frozen=True)
class MonthlyRankingRule:
    """
    The ranking at a decision session's close. The universe is every stock (no ETF) that traded that session, closed at
    `min_close` or more, and traded `min_traded_value` a session on average over the last `traded_value_sessions`
    sessions, a session without a trade counting 0. Each of its stocks has a revenue acceleration, the mean revenue of
    the latest `short_months` over that of the latest `long_months` up to the month read, none if any of them is
    missing, and a nearness to its high, its total-return level over the highest of the last `high_sessions` sessions,
    none while its first bar is later than the first of them: a few sessions since a listing hold no such high.
    Each factor is ranked among the stocks that have it (`ranks`), the score is the sum of the two ranks, and the `top`
    best scores are the ranking. Prices are as listed, so a past close is the price it traded at.
    """

    top: PositiveInt
    min_close: NonNegativeFloat
    min_traded_value: NonNegativeFloat
    traded_value_sessions: PositiveInt
    high_sessions: PositiveInt
    short_months: PositiveInt
    long_months: PositiveInt

    @model_validator(mode="after")
    def the_short_months_are_among_the_long(self) -> Self:
        if self.short_months > self.long_months:
            raise ValueError("short_months must not be more than long_months")

        return self

    def apply(self, history: RankingHistory, column: int, revenue_month: date, names: Mapping[str, str | None]) -> Ranking:
        universe = in_universe(history.bars, column, self.min_close, self.min_traded_value, self.traded_value_sessions)
        month = revenue_column(history, revenue_month)
        acceleration = np.where(universe, revenue_acceleration(history.revenue, month, self.short_months, self.long_months), np.nan)
        nearness = np.where(universe, nearness_to_high(history, column, self.high_sessions), np.nan)
        acceleration_rank, nearness_rank = ranks(acceleration), ranks(nearness)
        score = acceleration_rank + nearness_rank
        scored = np.flatnonzero(~np.isnan(score))
        best = scored[np.argsort(-score[scored], kind="stable")][: self.top]
        stocks = [
            RankedStock(
                stock_id=history.bars.stock_ids[row],
                stock_name=names.get(history.bars.stock_ids[row]),
                revenue_acceleration=float(acceleration[row]),
                nearness_to_high=float(nearness[row]),
                acceleration_rank=float(acceleration_rank[row]),
                nearness_rank=float(nearness_rank[row]),
                score=float(score[row]),
            )
            for row in best.tolist()
        ]

        return Ranking(
            decided_on=history.bars.sessions[column],
            revenue_month=revenue_month,
            universe=int(universe.sum()),
            scored=len(scored),
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
