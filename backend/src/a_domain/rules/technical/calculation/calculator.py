from collections.abc import Iterable, Sequence
from functools import reduce
from typing import Annotated, Literal, Self

import numpy as np
from pydantic import ConfigDict, Field, model_validator
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.types.enums import IndicatorKind, IndicatorOutput, MarketField
from a_domain.types.values import Floats, IndicatorPeriod, Integers

type Outputs = dict[IndicatorOutput, Floats]


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class MovingAverageIndicator:
    """`sma` averages the daily closes, `volume_sma` the daily volumes. Both include the bar they are read at."""

    kind: Literal[IndicatorKind.SMA, IndicatorKind.VOLUME_SMA]
    period: IndicatorPeriod

    @property
    def required_bars(self) -> int:
        return self.period


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class PeriodIndicator:
    kind: Literal[IndicatorKind.RSI, IndicatorKind.ADX, IndicatorKind.ATR, IndicatorKind.OBV, IndicatorKind.MFI]
    period: IndicatorPeriod

    @property
    def required_bars(self) -> int:
        match self.kind:
            case IndicatorKind.ADX:
                return self.period * 2
            case IndicatorKind.OBV:
                return self.period
            case _:
                return self.period + 1


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class MacdIndicator:
    kind: Literal[IndicatorKind.MACD]
    fast: IndicatorPeriod
    slow: IndicatorPeriod
    signal: IndicatorPeriod

    @model_validator(mode="after")
    def periods_are_ordered(self) -> Self:
        if self.fast >= self.slow:
            raise ValueError("the MACD slow period must be longer than the fast one")

        return self

    @property
    def required_bars(self) -> int:
        return self.slow + self.signal - 1


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class BollingerIndicator:
    kind: Literal[IndicatorKind.BOLLINGER]
    period: IndicatorPeriod
    std: Annotated[float, Field(gt=0, le=10, allow_inf_nan=False, strict=True)]

    @property
    def required_bars(self) -> int:
        return self.period


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class StochasticIndicator:
    kind: Literal[IndicatorKind.STOCHASTIC]
    k_period: IndicatorPeriod
    d_period: IndicatorPeriod

    @property
    def required_bars(self) -> int:
        return self.k_period + self.d_period - 1


type IndicatorParameters = Annotated[
    MovingAverageIndicator | PeriodIndicator | MacdIndicator | BollingerIndicator | StochasticIndicator, Field(discriminator="kind")
]
"""One indicator's kind and parameters, such as `{"kind": "sma", "period": 37}`. required_bars is the history it reads."""


def indicator_series(parameters: IndicatorParameters, bars: Sequence[Ohlcv]) -> list[dict[IndicatorOutput, float]]:
    """
    The indicator's outputs at each of `bars`, oldest first, each over the bars up to that one: what a chart draws of
    what a strategy reads. A bar with fewer than required_bars bars up to it has none, and an output that is not
    finite is absent.
    """
    count, first = len(bars), parameters.required_bars - 1

    if count <= first:
        return [{} for _ in bars]

    windows = np.broadcast_to(np.arange(count)[:, None], (count, count))

    with np.errstate(all="ignore"):
        [outputs] = indicator_outputs(parameters, stacked_bars(bars), windows, np.arange(count), np.arange(1, count + 1), [0]).values()

    readings = [
        {output: float(values[bar]) for output, values in outputs.items() if not np.isnan(values[bar])} for bar in range(count)
    ]
    return [{} for _ in range(first)] + readings[first:]


def stacked_bars(bars: Sequence[Ohlcv]) -> dict[MarketField, Floats]:
    """Each field of the bars as one array, oldest first, as indicator_outputs reads them."""
    return {field: np.array([float(getattr(bar, field)) for bar in bars], dtype=np.float64) for field in MarketField}


def indicator_outputs(
    parameters: IndicatorParameters,
    bars: dict[MarketField, Floats],
    windows: Integers,
    ends: Integers,
    lengths: Integers,
    shifts: Iterable[int],
) -> dict[int, Outputs]:
    """
    The indicator's outputs at each window's bar `bars_ago` before its latest, for each `bars_ago` of `shifts`: NaN
    where the window's bars cannot give one or it is not finite. Window `i` is the `lengths[i]` bars of `bars` up to
    `ends[i]`, and `windows` holds each window's bar positions from its first, one row per position and one column
    per window.
    """
    match parameters:
        case MovingAverageIndicator() | BollingerIndicator() | StochasticIndicator() | PeriodIndicator(kind=IndicatorKind.MFI):
            series = latest_series(parameters, bars)
            read = {bars_ago: {output: values[ends - bars_ago] for output, values in series.items()} for bars_ago in shifts}
        case PeriodIndicator() | MacdIndicator():
            read = running_outputs(parameters, bars, windows, {bars_ago: lengths - 1 - bars_ago for bars_ago in shifts})

    return {bars_ago: {output: finite(values) for output, values in outputs.items()} for bars_ago, outputs in read.items()}


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
    branch, without a branch. numpy's pairwise sum rounds apart, so a rule such as `close > sma` could flip on another
    bar; tests/test_strategy_goldens.py holds every indicator to the bits the strategies were checked on.
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
    """100 - 100 / (1 + gain / loss): 50 when both are 0, else 100 when the loss is, else 0 when the gain is."""
    value = 100 - (100 / (1 + average_gain / average_loss))
    value = np.where(average_gain == 0, 0.0, value)
    value = np.where(average_loss == 0, 100.0, value)
    return np.where((average_gain == 0) & (average_loss == 0), 50.0, value)


def previous(series: Floats) -> Floats:
    """Each bar's previous value; the first bar has none and reads NaN, which compares false."""
    return np.concatenate([np.full_like(series[:1], np.nan), series[:-1]])


def ema(values: Floats, first: int, period: int) -> Floats:
    """The exponential average of the values from position `first` on, from the plain average of its first `period`."""
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
    """The sum of the first `period` values from position `first`, then less a period's share of itself plus each later value."""
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
    """The on-balance volume from each window's first bar, which adds nothing; each later bar adds its signed volume."""
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
