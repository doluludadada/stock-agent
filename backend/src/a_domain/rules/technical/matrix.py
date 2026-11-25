from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from itertools import pairwise
from math import ceil
from typing import Self

import numpy as np
from pydantic import ConfigDict, model_validator
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.rules.technical.strategy import TechnicalRule, TechnicalScoring, TechnicalStrategy, rule_results
from a_domain.types.enums import MarketField, RuleEffect
from a_domain.types.values import Flags, Floats, Integers


@dataclass(frozen=True, config=ConfigDict(arbitrary_types_allowed=True))
class DailyBarMatrix:
    """
    Every stock's daily bars over the same sessions, oldest first: one row per stock, one column per session, NaN in
    every field where the stock has no bar of that session. Volume is in shares.
    """

    stock_ids: tuple[str, ...]
    sessions: tuple[date, ...]
    open: Floats
    high: Floats
    low: Floats
    close: Floats
    volume: Floats

    @model_validator(mode="after")
    def one_bar_per_cell(self) -> Self:
        shape = (len(self.stock_ids), len(self.sessions))

        if any(values.shape != shape or values.dtype != np.float64 for values in self.fields.values()):
            raise ValueError(f"every field needs float64 values in the shape (stocks, sessions) {shape}")

        if any((np.isnan(values) != np.isnan(self.close)).any() for values in self.fields.values()):
            raise ValueError("a session without a bar of the stock is NaN in every field, and a bar has every field")

        if any(earlier >= later for earlier, later in pairwise(self.sessions)):
            raise ValueError("the sessions run oldest first, each once")

        return self

    @property
    def fields(self) -> dict[MarketField, Floats]:
        return {
            MarketField.OPEN: self.open,
            MarketField.HIGH: self.high,
            MarketField.LOW: self.low,
            MarketField.CLOSE: self.close,
            MarketField.VOLUME: self.volume,
        }


@dataclass(frozen=True)
class DailyBarMatrixRule:
    """Every stock's daily bars as one matrix: the stocks in id order, and one column per session any of them traded."""

    def apply(self, history: Mapping[str, Sequence[Ohlcv]], trading_date: Callable[[datetime], date]) -> DailyBarMatrix:
        days = {stamp: trading_date(stamp) for stamp in {bar.ts for bars in history.values() for bar in bars}}
        sessions = tuple(sorted(set(days.values())))
        columns = {session: column for column, session in enumerate(sessions)}
        stock_ids = tuple(sorted(history))
        cells = {name: np.full((len(stock_ids), len(sessions)), np.nan) for name in ("open", "high", "low", "close", "volume")}

        for row, stock_id in enumerate(stock_ids):
            held = [columns[days[bar.ts]] for bar in history[stock_id]]

            for name, values in cells.items():
                values[row, held] = [getattr(bar, name) for bar in history[stock_id]]

        return DailyBarMatrix(stock_ids=stock_ids, sessions=sessions, **cells)


def last_closes(close: np.ndarray) -> np.ndarray:
    """Each row's latest value at or before each column: NaN only before the row's first value."""
    columns = np.where(np.isnan(close), 0, np.arange(close.shape[1]))
    np.maximum.accumulate(columns, axis=1, out=columns)

    return np.take_along_axis(close, columns, axis=1)


@dataclass(frozen=True, config=ConfigDict(arbitrary_types_allowed=True))
class StrategyScores:
    """The matrix's shape: each stock's technical score and pass at each session, 0 and False where it has no bar."""

    score: Integers
    passed: Flags


@dataclass(frozen=True)
class StrategyScoresRule:
    """
    The strategy's report on every stock at every session at once: what TechnicalStrategy.apply reports on the stock's
    bars of the session's history window, with the session's close as the latest price.
    """

    strategy: TechnicalStrategy

    def apply(self, bars: DailyBarMatrix, window_starts: Sequence[int]) -> StrategyScores:
        """`window_starts[t]` is the column of the first session of the window that session `t` reads."""
        present = ~np.isnan(bars.close)
        lengths = window_lengths(present, window_starts)
        stacked = {field: values[present] for field, values in bars.fields.items()}
        scored = np.flatnonzero(lengths >= self.strategy.required_bars)
        score, passed = np.zeros(len(lengths), dtype=np.int64), np.zeros(len(lengths), dtype=np.bool_)

        for batch in batches(scored, lengths):
            results = rule_results(self.strategy, stacked, batch, lengths[batch], stacked[MarketField.CLOSE][batch])
            score[batch], passed[batch] = scores(self.strategy.scoring, self.strategy.rules, results)

        score_matrix, passed_matrix = np.zeros(present.shape, dtype=np.int64), np.zeros(present.shape, dtype=np.bool_)
        score_matrix[present], passed_matrix[present] = score, passed
        return StrategyScores(score=score_matrix, passed=passed_matrix)


def window_lengths(present: Flags, window_starts: Sequence[int]) -> Integers:
    """How many bars each bar's window holds, for each bar of the matrix stock after stock."""
    starts = np.asarray(window_starts, dtype=np.int64)
    sessions = np.arange(present.shape[1])

    if starts.shape != sessions.shape or (starts < 0).any() or (starts > sessions).any():
        raise ValueError("window_starts needs one column per session, at or before that session")

    counts = np.cumsum(present, axis=1)
    return (counts - (counts - present)[:, starts])[present]


def batches(rows: Integers, lengths: Integers) -> list[Integers]:
    """The rows in batches whose windows hold about a million values per field, so memory stays bounded."""
    if not len(rows):
        return []

    return np.array_split(rows, ceil(len(rows) * int(lengths.max()) / 2**20))


def scores(
    scoring: TechnicalScoring, rules: Sequence[TechnicalRule], results: Sequence[tuple[Flags, Flags]]
) -> tuple[Integers, Flags]:
    """TechnicalScoring.apply for every window, and score 0 with a failure where a rule read an unavailable input."""
    score = np.full(len(results[0][0]), scoring.base_score, dtype=np.int64)
    blocked, available = np.zeros(len(score), dtype=np.bool_), np.ones(len(score), dtype=np.bool_)

    for rule, (holds, rule_available) in zip(rules, results, strict=True):
        available &= rule_available

        match rule.effect:
            case RuleEffect.BLOCK_ON_FAIL:
                score -= scoring.block_failure_penalty * ~holds
                blocked |= ~holds
            case RuleEffect.REDUCE_SCORE_ON_FAIL:
                score -= scoring.failure_score_reduction * ~holds
            case RuleEffect.INCREASE_SCORE_ON_PASS:
                score += scoring.pass_score_increase * holds

    return np.where(available, np.clip(score, 0, 100), 0), available & ~blocked
