from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime
from functools import reduce
from itertools import pairwise
from math import ceil
from typing import Self

import numpy as np
from numpy.typing import NDArray
from pydantic import ConfigDict, model_validator
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.rules.technical.calculation.calculator import (
    BollingerIndicator,
    IndicatorParameters,
    MacdIndicator,
    MovingAverageIndicator,
    PeriodIndicator,
    StochasticIndicator,
)
from a_domain.rules.technical.formula import (
    Arithmetic,
    Comparison,
    Condition,
    ConditionGroup,
    IndicatorValue,
    LatestPrice,
    MarketValue,
    NumericExpression,
    references,
)
from a_domain.rules.technical.strategy import TechnicalRule, TechnicalScoring, TechnicalStrategy
from a_domain.types.enums import (
    ArithmeticOperator,
    ComparisonOperator,
    GroupOperator,
    IndicatorKind,
    IndicatorOutput,
    MarketField,
    RuleEffect,
)
from a_domain.types.values import FormulaId

type Floats = NDArray[np.float64]
type Flags = NDArray[np.bool_]
type Integers = NDArray[np.int64]
type Outputs = dict[IndicatorOutput, Floats]


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


@dataclass(frozen=True, config=ConfigDict(arbitrary_types_allowed=True))
class WindowInputs:
    """
    What the formulas read for a batch of windows: the stacked bars the batch reaches; the index there of each window's
    latest bar; and each indicator output the formulas read, keyed by indicator id and bars ago. NaN stands for an input
    the window cannot give, as None does in FormulaInputs.
    """

    bars: dict[MarketField, Floats]
    ends: Integers
    indicators: dict[tuple[FormulaId, int], Outputs]


@dataclass(frozen=True)
class StrategyScoresRule:
    """
    The strategy's report on every stock at every session at once: what TechnicalStrategy.apply reports on the stock's
    bars of the session's history window, with the session's close as the latest price. Each formula runs operation by
    operation as the scalar code does, so a rule such as `close > sma` flips on the same last bit.
    """

    strategy: TechnicalStrategy

    def apply(self, bars: DailyBarMatrix, window_starts: Sequence[int]) -> StrategyScores:
        """`window_starts[t]` is the column of the first session of the window that session `t` reads."""
        present = ~np.isnan(bars.close)
        lengths = window_lengths(present, window_starts)
        stacked = {field: values[present] for field, values in bars.fields.items()}
        scored = np.flatnonzero(lengths >= self.strategy.required_bars)
        shifts = indicator_shifts(self.strategy.rules)
        score, passed = np.zeros(len(lengths), dtype=np.int64), np.zeros(len(lengths), dtype=np.bool_)

        for batch in batches(scored, lengths):
            score[batch], passed[batch] = batch_scores(self.strategy, shifts, stacked, batch, lengths[batch])

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


def indicator_shifts(rules: Sequence[TechnicalRule]) -> dict[FormulaId, set[int]]:
    """How many bars back the rules read each indicator: TechnicalStrategy.apply's `read`."""
    shifts: dict[FormulaId, set[int]] = {}

    for rule in rules:
        for reference, shift in references(rule.condition):
            if isinstance(reference, IndicatorValue):
                shifts.setdefault(reference.indicator_id, set()).add(reference.bars_ago + shift)

    return shifts


def batches(rows: Integers, lengths: Integers) -> list[Integers]:
    """The rows in batches whose windows hold about a million values per field, so memory stays bounded."""
    if not len(rows):
        return []

    return np.array_split(rows, ceil(len(rows) * int(lengths.max()) / 2**20))


def batch_scores(
    strategy: TechnicalStrategy, shifts: dict[FormulaId, set[int]], bars: dict[MarketField, Floats], ends: Integers, lengths: Integers
) -> tuple[Integers, Flags]:
    """The batch's scores, read from the stacked bars from the batch's first window on."""
    first = int((ends - lengths).min()) + 1
    span = {field: values[first : int(ends.max()) + 1] for field, values in bars.items()}
    latest = ends - first

    with np.errstate(all="ignore"):
        windows = np.minimum(latest - lengths + 1 + np.arange(int(lengths.max()))[:, None], len(span[MarketField.CLOSE]) - 1)
        indicators = {
            (indicator_id, bars_ago): {output: finite(values) for output, values in outputs.items()}
            for indicator_id, reads in shifts.items()
            for bars_ago, outputs in indicator_outputs(
                strategy.indicators[indicator_id], span, windows, latest, lengths, reads
            ).items()
        }
        inputs = WindowInputs(bars=span, ends=latest, indicators=indicators)
        return scores(strategy.scoring, strategy.rules, [condition_holds(rule.condition, inputs) for rule in strategy.rules])


def indicator_outputs(
    parameters: IndicatorParameters,
    bars: dict[MarketField, Floats],
    windows: Integers,
    ends: Integers,
    lengths: Integers,
    shifts: Iterable[int],
) -> dict[int, Outputs]:
    """
    calculator.calculated_outputs over each window's bars up to `bars_ago` before its latest, for each of `shifts`.
    `windows` holds each window's bar positions from its first, one row per position and one column per window.
    """
    match parameters:
        case MovingAverageIndicator() | BollingerIndicator() | StochasticIndicator() | PeriodIndicator(kind=IndicatorKind.MFI):
            series = latest_series(parameters, bars)
            return {bars_ago: {output: values[ends - bars_ago] for output, values in series.items()} for bars_ago in shifts}
        case PeriodIndicator() | MacdIndicator():
            return running_outputs(parameters, bars, windows, {bars_ago: lengths - 1 - bars_ago for bars_ago in shifts})


def latest_series(
    parameters: MovingAverageIndicator | BollingerIndicator | StochasticIndicator | PeriodIndicator, bars: dict[MarketField, Floats]
) -> Outputs:
    """
    An indicator that reads only its last few bars, at each bar: the same in every window that holds those bars, so it
    is computed once per bar. The PeriodIndicator that reaches here is the MFI.
    """
    match parameters:
        case MovingAverageIndicator(kind=kind, period=period):
            values = bars[MarketField.CLOSE if kind == IndicatorKind.SMA else MarketField.VOLUME]
            return {IndicatorOutput.VALUE: latest_sma(values, period)}
        case BollingerIndicator(period=period, std=std):
            return latest_bollinger(bars[MarketField.CLOSE], period, std)
        case StochasticIndicator(k_period=k_period, d_period=d_period):
            return latest_stochastic(bars, k_period, d_period)
        case PeriodIndicator(period=period):
            return {IndicatorOutput.VALUE: latest_mfi(bars, period)}


def running_outputs(
    parameters: PeriodIndicator | MacdIndicator, bars: dict[MarketField, Floats], windows: Integers, positions: dict[int, Integers]
) -> dict[int, Outputs]:
    """
    An indicator that carries a state from bar to bar, seeded at each window's first bar, read at each window position
    in `positions` by bars ago. What one bar adds, such as its true range, depends only on that bar and the one before,
    so it is computed once per bar and gathered into the windows.
    """
    match parameters:
        case PeriodIndicator(kind=IndicatorKind.RSI, period=period):
            gains, losses = rsi_averages(bars[MarketField.CLOSE], windows, period)
            return {
                bars_ago: {IndicatorOutput.VALUE: oscillator(at(gains, read), at(losses, read))}
                for bars_ago, read in positions.items()
            }
        case PeriodIndicator(kind=IndicatorKind.ATR, period=period):
            series = {IndicatorOutput.VALUE: wilder_average(true_ranges(bars)[windows], 1, period)}
        case PeriodIndicator(kind=IndicatorKind.ADX, period=period):
            series = adx_series(bars, windows, period)
        case PeriodIndicator(period=period):
            obv = obv_series(bars, windows)
            return {
                bars_ago: {IndicatorOutput.VALUE: at(obv, read), IndicatorOutput.MOVING_AVERAGE: obv_average(obv, read, period)}
                for bars_ago, read in positions.items()
            }
        case MacdIndicator(fast=fast, slow=slow, signal=signal):
            series = macd_series(bars[MarketField.CLOSE][windows], fast, slow, signal)

    return {bars_ago: {output: at(values, read) for output, values in series.items()} for bars_ago, read in positions.items()}


def at(series: Floats, positions: Integers) -> Floats:
    return series[positions, np.arange(len(positions))]


def finite(values: Floats) -> Floats:
    return np.where(np.isfinite(values), values, np.nan)


def python_sum(terms: Iterable[Floats]) -> Floats:
    """
    sum() of the terms as CPython 3.12 and later adds floats: it carries each addition's exact rounding error and adds
    their total at the end unless it is not finite. Knuth's two-sum yields the same exact error as CPython's Neumaier
    branch, without a branch.
    """
    iterator = iter(terms)
    total = 0.0 + next(iterator)
    error = np.zeros_like(total)

    for term in iterator:
        added = total + term
        rounded_term = added - total
        error += (total - (added - rounded_term)) + (term - rounded_term)
        total = added

    return np.where((error != 0) & np.isfinite(error), total + error, total)


def python_max(first: Floats | float, second: Floats | float) -> Floats:
    """max(first, second): the second only when it is greater, so a NaN first stays and a NaN second never wins."""
    return np.where(second > first, second, first)


def python_min(first: Floats | float, second: Floats | float) -> Floats:
    return np.where(second < first, second, first)


def python_square(values: Floats) -> Floats:
    """x ** 2 as CPython computes it, through the C library's pow, which can round apart from x * x; numpy squares a scalar 2."""
    return np.power(values, np.full_like(values, 2.0))


def trailing(values: Floats, count: int) -> list[Floats]:
    """
    The `count` values up to each bar that has as many, oldest first: the i-th array holds, for each such bar, the
    value i bars after the first of them.
    """
    return [values[index : len(values) - count + 1 + index] for index in range(count)]


def aligned(series: Floats, count: int) -> Floats:
    """A series computed over `count` bars back to each bar, placed at its bar; NaN before the first such bar."""
    return np.concatenate([np.full(count - 1, np.nan), series])


def latest_sma(values: Floats, period: int) -> Floats:
    return aligned(python_sum(trailing(values, period)) / period, period)


def latest_bollinger(closes: Floats, period: int, std_multiplier: float) -> Outputs:
    window = trailing(closes, period)
    middle = python_sum(window) / period
    variance = python_sum(python_square(value - middle) for value in window) / period
    deviation = np.sqrt(variance)
    upper = middle + (std_multiplier * deviation)
    lower = middle - (std_multiplier * deviation)
    width = upper - lower
    outputs = {
        IndicatorOutput.UPPER: upper,
        IndicatorOutput.MIDDLE: middle,
        IndicatorOutput.LOWER: lower,
        IndicatorOutput.BANDWIDTH: np.where(middle == 0, 0.0, width / middle),
        IndicatorOutput.PERCENT_B: np.where(width == 0, 0.5, (window[-1] - lower) / width),
    }
    return {output: aligned(values, period) for output, values in outputs.items()}


def latest_stochastic(bars: dict[MarketField, Floats], k_period: int, d_period: int) -> Outputs:
    highest_high = reduce(python_max, trailing(bars[MarketField.HIGH], k_period))
    lowest_low = reduce(python_min, trailing(bars[MarketField.LOW], k_period))
    price_range = highest_high - lowest_low
    percent_k = np.where(price_range == 0, 50.0, ((bars[MarketField.CLOSE][k_period - 1 :] - lowest_low) / price_range) * 100)
    k_values = python_max(0.0, python_min(100.0, percent_k))

    return {
        IndicatorOutput.PERCENT_K: aligned(k_values, k_period),
        IndicatorOutput.PERCENT_D: aligned(python_sum(trailing(k_values, d_period)) / d_period, k_period + d_period - 1),
    }


def latest_mfi(bars: dict[MarketField, Floats], period: int) -> Floats:
    typical_price = (bars[MarketField.HIGH] + bars[MarketField.LOW] + bars[MarketField.CLOSE]) / 3
    prices, flows = trailing(typical_price, period + 1), trailing(typical_price * bars[MarketField.VOLUME], period + 1)
    positive_flow, negative_flow = np.zeros(len(prices[0])), np.zeros(len(prices[0]))

    for index in range(1, period + 1):
        positive_flow = np.where(prices[index] > prices[index - 1], positive_flow + flows[index], positive_flow)
        negative_flow = np.where(prices[index] < prices[index - 1], negative_flow + flows[index], negative_flow)

    return aligned(oscillator(positive_flow, negative_flow), period + 1)


def oscillator(average_gain: Floats, average_loss: Floats) -> Floats:
    """formulas._oscillator_from_average_gain_loss: 50 when both are 0, else 100 when the loss is, else 0 when the gain is."""
    value = 100 - (100 / (1 + average_gain / average_loss))
    value = np.where(average_gain == 0, 0.0, value)
    value = np.where(average_loss == 0, 100.0, value)
    return np.where((average_gain == 0) & (average_loss == 0), 50.0, value)


def previous(series: Floats) -> Floats:
    """Each bar's previous value; the first bar has none and reads NaN, which compares false."""
    return np.concatenate([np.full_like(series[:1], np.nan), series[:-1]])


def ema(values: Floats, first: int, period: int) -> Floats:
    """formulas.ema_series over the values from position `first` on."""
    series = np.full_like(values, np.nan)
    alpha = 2 / (period + 1)
    average = python_sum(values[first : first + period]) / period
    series[first + period - 1] = average

    for index in range(first + period, len(values)):
        average = (values[index] * alpha) + (average * (1 - alpha))
        series[index] = average

    return series


def wilder_average(values: Floats, first: int, period: int) -> Floats:
    """The average of the first `period` values from position `first`, then each later value folded in as RSI, ATR and ADX do."""
    series = np.full_like(values, np.nan)
    average = python_sum(values[first : first + period]) / period
    series[first + period - 1] = average

    for index in range(first + period, len(values)):
        average = ((average * (period - 1)) + values[index]) / period
        series[index] = average

    return series


def wilder_total(values: Floats, first: int, period: int) -> Floats:
    """The sum of the first `period` values from position `first`, then smoothed as formulas._smoothed_adx does."""
    series = np.full_like(values, np.nan)
    total = python_sum(values[first : first + period])
    series[first + period - 1] = total

    for index in range(first + period, len(values)):
        total = total - (total / period) + values[index]
        series[index] = total

    return series


def rsi_averages(closes: Floats, windows: Integers, period: int) -> tuple[Floats, Floats]:
    """Each window's average gain and loss: a bar's change is from the bar before it, which no window's first bar reads."""
    changes = closes - previous(closes)
    gains, losses = python_max(changes, 0.0), python_max(-changes, 0.0)
    return wilder_average(gains[windows], 1, period), wilder_average(losses[windows], 1, period)


def true_ranges(bars: dict[MarketField, Floats]) -> Floats:
    high, low, previous_close = bars[MarketField.HIGH], bars[MarketField.LOW], previous(bars[MarketField.CLOSE])
    return python_max(python_max(high - low, np.abs(high - previous_close)), np.abs(low - previous_close))


def adx_series(bars: dict[MarketField, Floats], windows: Integers, period: int) -> Outputs:
    high, low = bars[MarketField.HIGH], bars[MarketField.LOW]
    up_move, down_move = high - previous(high), previous(low) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    smoothed_tr, smoothed_plus_dm, smoothed_minus_dm = (
        wilder_total(values[windows], 1, period) for values in (true_ranges(bars), plus_dm, minus_dm)
    )
    no_range = smoothed_tr <= 0
    plus_di = np.where(no_range, 0.0, 100 * (smoothed_plus_dm / smoothed_tr))
    minus_di = np.where(no_range, 0.0, 100 * (smoothed_minus_dm / smoothed_tr))
    total_di = plus_di + minus_di
    dx = np.where(total_di == 0, 0.0, 100 * (np.abs(plus_di - minus_di) / total_di))
    return {
        IndicatorOutput.ADX: wilder_average(dx, period, period),
        IndicatorOutput.PLUS_DI: plus_di,
        IndicatorOutput.MINUS_DI: minus_di,
    }


def obv_series(bars: dict[MarketField, Floats], windows: Integers) -> Floats:
    """formulas.obv_series's running total from each window's first bar, which adds nothing; each later bar adds its signed volume."""
    closes, earlier, volumes = bars[MarketField.CLOSE], previous(bars[MarketField.CLOSE]), bars[MarketField.VOLUME]
    flows = np.where(closes > earlier, volumes, np.where(closes < earlier, -volumes, 0.0))[windows]
    flows[0] = 0.0
    return np.cumsum(flows, axis=0)


def obv_average(obv: Floats, positions: Integers, period: int) -> Floats:
    return python_sum(at(obv, positions - period + 1 + index) for index in range(period)) / period


def macd_series(closes: Floats, fast: int, slow: int, signal: int) -> Outputs:
    lines = ema(closes, 0, fast) - ema(closes, 0, slow)
    signals = ema(lines, slow - 1, signal)
    return {IndicatorOutput.LINE: lines, IndicatorOutput.SIGNAL: signals, IndicatorOutput.HISTOGRAM: lines - signals}


def condition_holds(condition: Condition, inputs: WindowInputs) -> tuple[Flags, Flags]:
    """Where the condition holds, and where every input it reads is available: formula.condition_holds's None is False."""
    match condition:
        case ConditionGroup(operator=operator, conditions=conditions):
            results = [condition_holds(part, inputs) for part in conditions]
            combine = np.logical_and if operator == GroupOperator.ALL else np.logical_or
            return reduce(combine, (holds for holds, _ in results)), reduce(np.logical_and, (available for _, available in results))
        case Comparison():
            return comparison_holds(condition, inputs)


def comparison_holds(comparison: Comparison, inputs: WindowInputs) -> tuple[Flags, Flags]:
    left, right = numeric_value(comparison.left, inputs), numeric_value(comparison.right, inputs)
    available = ~np.isnan(left) & ~np.isnan(right)

    match comparison.operator:
        case ComparisonOperator.GT:
            return left > right, available
        case ComparisonOperator.GTE:
            return left >= right, available
        case ComparisonOperator.LT:
            return left < right, available
        case ComparisonOperator.LTE:
            return left <= right, available
        case ComparisonOperator.EQ:
            return left == right, available
        case ComparisonOperator.NE:
            return left != right, available
        case _:
            return crossing_holds(comparison, inputs, left, right)


def crossing_holds(comparison: Comparison, inputs: WindowInputs, left: Floats, right: Floats) -> tuple[Flags, Flags]:
    earlier_left, earlier_right = numeric_value(comparison.left, inputs, 1), numeric_value(comparison.right, inputs, 1)
    available = ~np.isnan(left) & ~np.isnan(right) & ~np.isnan(earlier_left) & ~np.isnan(earlier_right)

    if comparison.operator == ComparisonOperator.CROSSES_ABOVE:
        return (earlier_left <= earlier_right) & (left > right), available

    return (earlier_left >= earlier_right) & (left < right), available


def numeric_value(expression: NumericExpression, inputs: WindowInputs, shift: int = 0) -> Floats:
    """formula.numeric_value for every window, NaN where it is None."""
    match expression:
        case MarketValue(field=field, bars_ago=bars_ago):
            return finite(inputs.bars[field][inputs.ends - bars_ago - shift])
        case LatestPrice():
            return finite(inputs.bars[MarketField.CLOSE][inputs.ends])
        case IndicatorValue(indicator_id=indicator_id, output=output, bars_ago=bars_ago):
            return inputs.indicators[(indicator_id, bars_ago + shift)][output]
        case Arithmetic(operator=operator, left=left, right=right):
            return arithmetic(operator, numeric_value(left, inputs, shift), numeric_value(right, inputs, shift))
        case _:
            return np.full(len(inputs.ends), float(expression))


def arithmetic(operator: ArithmeticOperator, left: Floats, right: Floats) -> Floats:
    match operator:
        case ArithmeticOperator.ADD:
            result = left + right
        case ArithmeticOperator.SUBTRACT:
            result = left - right
        case ArithmeticOperator.MULTIPLY:
            result = left * right
        case ArithmeticOperator.DIVIDE:
            result = np.where(right != 0, left / right, np.nan)

    return finite(result)


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
