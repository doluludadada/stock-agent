from bisect import bisect_right
from collections.abc import Mapping
from datetime import date
from statistics import fmean
from typing import Annotated, Self

import numpy as np
from pydantic import ConfigDict, Field, NonNegativeFloat, PositiveFloat, computed_field, model_validator
from pydantic.dataclasses import dataclass

from a_domain.model.trading.ranking_formula import RankingFormula
from a_domain.rules.technical.matrix import Flags, Floats
from a_domain.rules.trading.ranking import DecisionSessionsRule, MonthlyRankingRule, Ranking, RankingHistory
from a_domain.types.errors import BacktestPeriodUnavailable
from a_domain.types.values import NonEmptyText, max_drawdown

type Curve = Annotated[dict[date, float], Field(min_length=1)]


@dataclass(frozen=True, kw_only=True, config=ConfigDict(use_attribute_docstrings=True))
class RankingBacktest:
    """
    What holding each month's ranking would have done over past sessions, as fractions of what it started with, against
    the benchmark held over the same sessions. It placed no order and touched no account. Every *_return and drawdown is
    a fraction: 0.1 is 10%.
    """

    formula: RankingFormula
    """The formula whose rankings it held."""

    first: date
    last: date
    """The period asked: its decisions are the decision sessions from `first` to `last`, its sessions end at `last`."""

    benchmark_id: NonEmptyText
    fee_rate: NonNegativeFloat
    tax_rate: NonNegativeFloat
    """market.fee_rate on every BUY and SELL, and market.tax_rate on every SELL, when it ran."""

    sessions_per_year: PositiveFloat
    equity_curve: Curve
    """The portfolio's value at the close of its first decision, 1, and at the close of every session after it."""

    benchmark_curve: dict[date, float]
    """The benchmark's total-return level over the same sessions, 1 at the first one. Empty when the history lacks it."""

    rankings: list[Ranking]
    """Each decision's ranking, oldest first."""

    holdings: dict[date, list[str]]
    """The stocks held from the open of each session after a decision, best first, then those that could not be sold."""

    costs: NonNegativeFloat
    """The fees and the tax paid, each as a fraction of the value it was paid from, summed."""

    turnover: NonNegativeFloat | None
    """The share of the portfolio bought at a rebalance, on average over them. None when it never rebalanced."""

    @model_validator(mode="after")
    def the_benchmark_covers_the_same_sessions(self) -> Self:
        if self.benchmark_curve and self.benchmark_curve.keys() != self.equity_curve.keys():
            raise ValueError("the benchmark curve covers the equity curve's sessions")

        return self

    @computed_field
    @property
    def total_return(self) -> float:
        return curve_return(self.equity_curve)

    @computed_field
    @property
    def annual_return(self) -> float | None:
        """The compound annual return over the sessions after the first decision, sessions_per_year a year."""
        return annual(self.equity_curve, self.sessions_per_year)

    @computed_field
    @property
    def max_drawdown(self) -> float:
        return max_drawdown(self.equity_curve.values())

    @computed_field
    @property
    def yearly_returns(self) -> dict[int, float]:
        """Each calendar year's return, from the last close before it, or the start, to its last close."""
        return yearly(self.equity_curve)

    @computed_field
    @property
    def benchmark_total_return(self) -> float | None:
        return curve_return(self.benchmark_curve) if self.benchmark_curve else None

    @computed_field
    @property
    def benchmark_annual_return(self) -> float | None:
        return annual(self.benchmark_curve, self.sessions_per_year) if self.benchmark_curve else None

    @computed_field
    @property
    def benchmark_max_drawdown(self) -> float | None:
        return max_drawdown(self.benchmark_curve.values()) if self.benchmark_curve else None

    @computed_field
    @property
    def benchmark_yearly_returns(self) -> dict[int, float]:
        return yearly(self.benchmark_curve) if self.benchmark_curve else {}

    @computed_field
    @property
    def years_ahead(self) -> int | None:
        """The calendar years of yearly_returns it returned more than the benchmark. None when the history lacks the benchmark."""
        benchmark = self.benchmark_yearly_returns

        return sum(value > benchmark[year] for year, value in self.yearly_returns.items()) if benchmark else None


def curve_return(curve: dict[date, float]) -> float:
    return curve[next(reversed(curve))] / curve[next(iter(curve))] - 1


def annual(curve: dict[date, float], sessions_per_year: float) -> float | None:
    return (1 + curve_return(curve)) ** (sessions_per_year / (len(curve) - 1)) - 1 if len(curve) > 1 else None


def yearly(curve: dict[date, float]) -> dict[int, float]:
    ends = {session.year: value for session, value in curve.items()}
    starts = [next(iter(curve.values())), *list(ends.values())[:-1]]
    return {year: end / start - 1 for (year, end), start in zip(ends.items(), starts, strict=True)}


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class RankingBook:
    """What RankingBacktestRule keeps from session to session."""

    weights: Floats
    """Each stock's share of the portfolio, in the rows of the history's bars. What they leave of 1 is cash."""

    rankings: list[Ranking]
    curve: dict[date, float]
    holdings: dict[date, list[str]] = Field(default_factory=dict)
    bought: list[float] = Field(default_factory=list)
    """The share of the portfolio each rebalance bought."""

    equity: float = 1.0
    costs: float = 0.0


def replay(
    book: RankingBook, history: RankingHistory, decisions: Mapping[int, Ranking], columns: range, fee_rate: float, tax_rate: float
) -> None:
    sessions, traded = history.bars.sessions, ~np.isnan(history.bars.close)
    intraday = np.where(traded, history.bars.close / history.bars.open - 1, 0.0)

    for column in columns:
        if book.rankings[-1].decided_on == sessions[column - 1]:
            book.holdings[sessions[column]] = rebalance(
                book, history, traded[:, column], intraday[:, column], column, fee_rate, tax_rate
            )
        else:
            hold(book, history.returns[:, column])

        book.curve[sessions[column]] = book.equity

        if column in decisions:
            book.rankings.append(decisions[column])


def hold(book: RankingBook, returns: Floats) -> None:
    growth = 1 + float(book.weights @ returns)
    book.equity *= growth
    book.weights = book.weights * (1 + returns) / growth


def rebalance(
    book: RankingBook, history: RankingHistory, traded: Flags, intraday: Floats, column: int, fee_rate: float, tax_rate: float
) -> list[str]:
    """Trades at the session's open to the ranking's equal weights, then holds through its close; the stocks held."""
    hold(book, (1 + history.returns[:, column]) / (1 + intraday) - 1)
    drift = book.weights
    rows = [history.bars.stock_ids.index(stock.stock_id) for stock in book.rankings[-1].stocks]
    target = np.zeros(len(drift))
    target[rows] = 1 / len(rows) if rows else 0.0
    one_price = traded & (history.bars.high[:, column] == history.bars.low[:, column])
    target[(target > 0) & (~traded | (one_price & (drift == 0)))] = 0
    stuck = (drift > 0) & ~traded
    target[stuck] = drift[stuck]
    free = np.where(stuck, 0.0, target)

    if free.sum() > 0:
        free *= (1 - target[stuck].sum()) / free.sum()

    target = np.where(stuck, target, free)
    bought = np.clip(target - drift, 0, None).sum()
    charge = np.clip(drift - target, 0, None).sum() * (fee_rate + tax_rate) + bought * fee_rate
    book.equity *= 1 - charge
    book.costs += charge
    book.bought.append(float(bought))
    book.weights = target
    hold(book, intraday)
    held = [row for row in rows if target[row] > 0] + [row for row in np.flatnonzero(stuck).tolist() if row not in rows]

    return [history.bars.stock_ids[row] for row in held]


def benchmark_curve(history: RankingHistory, start: int, end: int, benchmark_id: NonEmptyText) -> dict[date, float]:
    if benchmark_id not in history.bars.stock_ids:
        return {}

    level = history.level[history.bars.stock_ids.index(benchmark_id), start : end + 1]
    return {session: float(value / level[0]) for session, value in zip(history.bars.sessions[start : end + 1], level, strict=True)}


@dataclass(frozen=True)
class RankingPortfolioRule:
    """
    Holds given rankings over past sessions on weights, as the research that found the ranking did: at the open of the
    session after each ranking's decision it sells what it no longer holds and holds the ranking's stocks in equal
    weights until the next one. A stock that does not trade that session, or opens on a bar of one price (a locked
    limit) without being held, is not bought, and the others share its weight; a held stock that does not trade is not
    sold and keeps its weight. Every trade pays fee_rate of what it moves, and every sale tax_rate too, out of the
    portfolio. Between rankings the weights drift with each stock's total return. What the weights leave of the
    portfolio is cash, which earns nothing: an empty ranking holds cash until the next one, and so does a ranking none
    of whose stocks can be bought, beside the holdings it could not sell. A held stock that never trades again keeps
    its weight at its last close: the history cannot tell a buyout from a failure. The benchmark is held over the same
    sessions by its total return. `rankings` holds each ranking by its decision session; one of a day the history holds
    no session of is left out, and with none left it raises BacktestPeriodUnavailable.
    """

    fee_rate: NonNegativeFloat
    tax_rate: NonNegativeFloat
    benchmark_id: NonEmptyText
    sessions_per_year: PositiveFloat

    def apply(self, history: RankingHistory, rankings: Mapping[date, Ranking], first: date, last: date) -> RankingBacktest:
        sessions = history.bars.sessions
        columns = {session: column for column, session in enumerate(sessions)}
        decisions = {columns[decided_on]: ranking for decided_on, ranking in rankings.items() if decided_on in columns}

        if not decisions:
            raise BacktestPeriodUnavailable(
                f"A ranking backtest needs a decision session from {first} to {last}, and the history holds "
                f"{f'{sessions[0]} to {sessions[-1]}' if sessions else 'no session'}."
            )

        start, end = min(decisions), bisect_right(sessions, last) - 1
        book = RankingBook(weights=np.zeros(len(history.bars.stock_ids)), rankings=[decisions[start]], curve={sessions[start]: 1.0})
        replay(book, history, decisions, range(start + 1, end + 1), self.fee_rate, self.tax_rate)

        return RankingBacktest(
            formula=decisions[start].formula,
            first=first,
            last=last,
            benchmark_id=self.benchmark_id,
            fee_rate=self.fee_rate,
            tax_rate=self.tax_rate,
            sessions_per_year=self.sessions_per_year,
            equity_curve=book.curve,
            benchmark_curve=benchmark_curve(history, start, end, self.benchmark_id),
            rankings=book.rankings,
            holdings=book.holdings,
            costs=book.costs,
            turnover=fmean(book.bought) if book.bought else None,
        )


@dataclass(frozen=True)
class RankingBacktestRule:
    """
    Replays the monthly ranking over a period: it ranks at the close of each decision session from `first` to `last`
    (DecisionSessionsRule, MonthlyRankingRule) and holds those rankings to `last` (RankingPortfolioRule). A period
    without a decision session raises BacktestPeriodUnavailable.
    """

    decision_rule: DecisionSessionsRule
    ranking_rule: MonthlyRankingRule
    portfolio_rule: RankingPortfolioRule

    def apply(self, history: RankingHistory, names: Mapping[str, str | None], first: date, last: date) -> RankingBacktest:
        sessions = history.bars.sessions
        rankings = {
            sessions[column]: self.ranking_rule.apply(history, column, month, names)
            for column, month in self.decision_rule.apply(sessions)
            if first <= sessions[column] <= last
        }

        return self.portfolio_rule.apply(history, rankings, first, last)
