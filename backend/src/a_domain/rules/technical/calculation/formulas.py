from collections.abc import Sequence
from math import sqrt

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.types.enums import IndicatorOutput


def latest_sma(values: Sequence[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None

    return sum(values[-period:]) / period


def ema_series(values: Sequence[float], period: int) -> list[float | None]:
    series: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return series

    alpha = 2 / (period + 1)
    previous = sum(values[:period]) / period
    series[period - 1] = previous

    for index in range(period, len(values)):
        previous = (values[index] * alpha) + (previous * (1 - alpha))
        series[index] = previous

    return series


def rsi_series(closes: Sequence[float], period: int) -> list[float | None]:
    series: list[float | None] = [None] * len(closes)
    if period <= 0 or len(closes) <= period:
        return series

    gains: list[float] = []
    losses: list[float] = []

    for index in range(1, period + 1):
        change = closes[index] - closes[index - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    series[period] = _oscillator_from_average_gain_loss(average_gain, average_loss)

    for index in range(period + 1, len(closes)):
        change = closes[index] - closes[index - 1]
        gain = max(change, 0)
        loss = max(-change, 0)
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
        series[index] = _oscillator_from_average_gain_loss(average_gain, average_loss)

    return series


def macd_series(closes: Sequence[float], fast: int, slow: int, signal_period: int) -> list[dict[IndicatorOutput, float]]:
    series: list[dict[IndicatorOutput, float]] = [{} for _ in closes]
    if min(fast, slow, signal_period) <= 0 or fast == slow:
        return series

    lines = [
        (index, fast_value - slow_value)
        for index, (fast_value, slow_value) in enumerate(zip(ema_series(closes, fast), ema_series(closes, slow), strict=True))
        if fast_value is not None and slow_value is not None
    ]

    for (index, line), signal in zip(lines, ema_series([line for _, line in lines], signal_period), strict=True):
        if signal is not None:
            series[index] = {IndicatorOutput.LINE: line, IndicatorOutput.SIGNAL: signal, IndicatorOutput.HISTOGRAM: line - signal}

    return series


def latest_bollinger(closes: Sequence[float], period: int, std_multiplier: float) -> dict[IndicatorOutput, float]:
    if period <= 0 or std_multiplier <= 0 or len(closes) < period:
        return {}

    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((value - middle) ** 2 for value in window) / period
    deviation = sqrt(variance)
    upper = middle + (std_multiplier * deviation)
    lower = middle - (std_multiplier * deviation)
    width = upper - lower
    bandwidth = 0.0 if middle == 0 else width / middle
    percent_b = 0.5 if width == 0 else (closes[-1] - lower) / width

    return {
        IndicatorOutput.UPPER: upper,
        IndicatorOutput.MIDDLE: middle,
        IndicatorOutput.LOWER: lower,
        IndicatorOutput.BANDWIDTH: bandwidth,
        IndicatorOutput.PERCENT_B: percent_b,
    }


def latest_stochastic(bars: Sequence[Ohlcv], k_period: int, d_period: int) -> dict[IndicatorOutput, float]:
    if min(k_period, d_period) <= 0 or len(bars) < k_period + d_period - 1:
        return {}

    k_values: list[float] = []

    for end in range(k_period - 1, len(bars)):
        window = bars[end - k_period + 1 : end + 1]
        highest_high = max(bar.high for bar in window)
        lowest_low = min(bar.low for bar in window)
        price_range = highest_high - lowest_low
        percent_k = 50.0 if price_range == 0 else ((bars[end].close - lowest_low) / price_range) * 100
        k_values.append(max(0.0, min(100.0, percent_k)))

    if len(k_values) < d_period:
        return {}

    return {IndicatorOutput.PERCENT_K: k_values[-1], IndicatorOutput.PERCENT_D: sum(k_values[-d_period:]) / d_period}


def atr_series(bars: Sequence[Ohlcv], period: int) -> list[float | None]:
    series: list[float | None] = [None] * len(bars)
    if period <= 0 or len(bars) <= period:
        return series

    ranges = _true_ranges(bars)
    atr = sum(ranges[:period]) / period
    series[period] = atr

    for index in range(period, len(ranges)):
        atr = ((atr * (period - 1)) + ranges[index]) / period
        series[index + 1] = atr

    return series


def adx_series(bars: Sequence[Ohlcv], period: int) -> list[dict[IndicatorOutput, float]]:
    if period <= 0 or len(bars) < period * 2:
        return [{} for _ in bars]

    plus_dms, minus_dms = _directional_movements(bars)
    return [{}, *_smoothed_adx(_true_ranges(bars), plus_dms, minus_dms, period)]


def obv_series(closes: Sequence[float], volumes: Sequence[float], ma_period: int) -> list[dict[IndicatorOutput, float]]:
    """On-balance volume and its moving average at each bar, from the first bar's zero."""
    series: list[dict[IndicatorOutput, float]] = [{} for _ in closes]
    if ma_period <= 0 or len(closes) != len(volumes):
        return series

    current_obv = 0.0
    obv_values = [current_obv]

    for index in range(1, len(closes)):
        if closes[index] > closes[index - 1]:
            current_obv += volumes[index]
        elif closes[index] < closes[index - 1]:
            current_obv -= volumes[index]

        obv_values.append(current_obv)

    for index in range(ma_period - 1, len(closes)):
        moving_average = sum(obv_values[index + 1 - ma_period : index + 1]) / ma_period
        series[index] = {IndicatorOutput.VALUE: obv_values[index], IndicatorOutput.MOVING_AVERAGE: moving_average}

    return series


def latest_mfi(bars: Sequence[Ohlcv], period: int) -> float | None:
    if period <= 0 or len(bars) <= period:
        return None

    positive_flow = 0.0
    negative_flow = 0.0

    for index in range(len(bars) - period, len(bars)):
        typical_price = _typical_price(bars[index])
        previous_typical_price = _typical_price(bars[index - 1])
        money_flow = typical_price * bars[index].volume

        if typical_price > previous_typical_price:
            positive_flow += money_flow
        elif typical_price < previous_typical_price:
            negative_flow += money_flow

    return _oscillator_from_average_gain_loss(positive_flow, negative_flow)


def _true_ranges(bars: Sequence[Ohlcv]) -> list[float]:
    return [_true_range(bars[index], bars[index - 1].close) for index in range(1, len(bars))]


def _true_range(bar: Ohlcv, previous_close: float) -> float:
    return max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close))


def _directional_movements(bars: Sequence[Ohlcv]) -> tuple[list[float], list[float]]:
    plus_dms: list[float] = []
    minus_dms: list[float] = []

    for index in range(1, len(bars)):
        up_move = bars[index].high - bars[index - 1].high
        down_move = bars[index - 1].low - bars[index].low
        plus_dms.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dms.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    return plus_dms, minus_dms


def _smoothed_adx(
    true_ranges: Sequence[float], plus_dms: Sequence[float], minus_dms: Sequence[float], period: int
) -> list[dict[IndicatorOutput, float]]:
    """The ADX and the directional indicators at each true range, once `period` directional indexes average into an ADX."""
    series: list[dict[IndicatorOutput, float]] = [{} for _ in true_ranges]
    smoothed_tr = sum(true_ranges[:period])
    smoothed_plus_dm = sum(plus_dms[:period])
    smoothed_minus_dm = sum(minus_dms[:period])

    dx_values: list[float] = []
    adx: float | None = None

    for index in range(period - 1, len(true_ranges)):
        if index >= period:
            smoothed_tr = smoothed_tr - (smoothed_tr / period) + true_ranges[index]
            smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm / period) + plus_dms[index]
            smoothed_minus_dm = smoothed_minus_dm - (smoothed_minus_dm / period) + minus_dms[index]

        dx, plus_di, minus_di = _directional_index(smoothed_tr, smoothed_plus_dm, smoothed_minus_dm)
        dx_values.append(dx)

        if len(dx_values) == period:
            adx = sum(dx_values) / period
        elif len(dx_values) > period and adx is not None:
            adx = ((adx * (period - 1)) + dx) / period

        if adx is not None:
            series[index] = {IndicatorOutput.ADX: adx, IndicatorOutput.PLUS_DI: plus_di, IndicatorOutput.MINUS_DI: minus_di}

    return series


def _directional_index(smoothed_tr: float, smoothed_plus_dm: float, smoothed_minus_dm: float) -> tuple[float, float, float]:
    if smoothed_tr <= 0:
        return 0.0, 0.0, 0.0

    plus_di = 100 * (smoothed_plus_dm / smoothed_tr)
    minus_di = 100 * (smoothed_minus_dm / smoothed_tr)
    total_di = plus_di + minus_di
    dx = 0.0 if total_di == 0 else 100 * (abs(plus_di - minus_di) / total_di)

    return dx, plus_di, minus_di


def _typical_price(bar: Ohlcv) -> float:
    return (bar.high + bar.low + bar.close) / 3


def _oscillator_from_average_gain_loss(average_gain: float, average_loss: float) -> float:
    if average_gain == 0 and average_loss == 0:
        return 50.0

    if average_loss == 0:
        return 100.0

    if average_gain == 0:
        return 0.0

    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))
