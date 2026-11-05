from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.rules.technical.calculation.formulas import (
    adx_series,
    atr_series,
    latest_bollinger,
    latest_mfi,
    latest_sma,
    latest_stochastic,
    macd_series,
    obv_series,
    rsi_series,
)
from a_domain.types.enums import IndicatorKind, IndicatorOutput
from a_domain.types.values import IndicatorPeriod


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
    def _periods_are_ordered(self) -> Self:
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


def indicator_outputs(parameters: IndicatorParameters, bars: Sequence[Ohlcv]) -> dict[IndicatorOutput, float]:
    """The indicator's outputs at the last of `bars`. An output the bars cannot give, or that is not finite, is absent."""
    return finite(calculated_outputs(parameters, bars, [bar.close for bar in bars], [float(bar.volume) for bar in bars]))


def indicator_series(parameters: IndicatorParameters, bars: Sequence[Ohlcv]) -> list[dict[IndicatorOutput, float]]:
    """
    The indicator's outputs at each of `bars`, each equal to indicator_outputs over the bars up to that one: what a
    chart draws. An indicator that reads only its last required_bars bars is read over that window at each bar; one
    that carries a state from bar to bar is computed in one pass.
    """
    closes, volumes = [bar.close for bar in bars], [float(bar.volume) for bar in bars]

    match parameters:
        case MovingAverageIndicator() | BollingerIndicator() | StochasticIndicator() | PeriodIndicator(kind=IndicatorKind.MFI):
            windows = ((max(0, end - parameters.required_bars), end) for end in range(1, len(bars) + 1))
            series = [calculated_outputs(parameters, bars[start:end], closes[start:end], volumes[start:end]) for start, end in windows]
        case PeriodIndicator() | MacdIndicator():
            series = running_series(parameters, bars, closes, volumes)

    return [finite(outputs) for outputs in series]


def finite(outputs: Mapping[IndicatorOutput, float | None]) -> dict[IndicatorOutput, float]:
    return {output: value for output, value in outputs.items() if value is not None and isfinite(value)}


def calculated_outputs(
    parameters: IndicatorParameters, bars: Sequence[Ohlcv], closes: Sequence[float], volumes: Sequence[float]
) -> Mapping[IndicatorOutput, float | None]:
    """Each output at the last bar by name. A one-output indicator's value is None when the bars cannot give it."""
    match parameters:
        case MovingAverageIndicator(kind=kind, period=period):
            return {IndicatorOutput.VALUE: latest_sma(closes if kind == IndicatorKind.SMA else volumes, period)}
        case PeriodIndicator(kind=IndicatorKind.MFI, period=period):
            return {IndicatorOutput.VALUE: latest_mfi(bars, period)}
        case BollingerIndicator(period=period, std=std):
            return latest_bollinger(closes, period, std)
        case StochasticIndicator(k_period=k_period, d_period=d_period):
            return latest_stochastic(bars, k_period, d_period)
        case PeriodIndicator() | MacdIndicator():
            series = running_series(parameters, bars, closes, volumes)
            return series[-1] if series else {}


def running_series(
    parameters: PeriodIndicator | MacdIndicator, bars: Sequence[Ohlcv], closes: Sequence[float], volumes: Sequence[float]
) -> Sequence[Mapping[IndicatorOutput, float | None]]:
    """Each bar's outputs of an indicator that carries a state from one bar to the next, computed in one pass."""
    match parameters:
        case PeriodIndicator(kind=IndicatorKind.RSI, period=period):
            return [{IndicatorOutput.VALUE: value} for value in rsi_series(closes, period)]
        case PeriodIndicator(kind=IndicatorKind.ATR, period=period):
            return [{IndicatorOutput.VALUE: value} for value in atr_series(bars, period)]
        case PeriodIndicator(kind=IndicatorKind.ADX, period=period):
            return adx_series(bars, period)
        case PeriodIndicator(period=period):
            return obv_series(closes, volumes, period)
        case MacdIndicator(fast=fast, slow=slow, signal=signal):
            return macd_series(closes, fast, slow, signal)
