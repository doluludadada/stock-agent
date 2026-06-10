from datetime import datetime, timedelta

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.rules.technical.calculation import IndicatorParameters, TechnicalIndicatorCalculator


def test_calculator_uses_configurable_indicator_periods() -> None:
    parameters = IndicatorParameters(
        rsi_period=7,
        macd_fast=5,
        macd_slow=10,
        macd_signal=4,
        ma_short=3,
        ma_mid=5,
        ma_long=8,
        bb_period=10,
        stoch_k=5,
        stoch_d=3,
        adx_period=7,
        atr_period=7,
        mfi_period=7,
    )

    indicators = TechnicalIndicatorCalculator(parameters).calculate(_sample_bars(40))

    assert indicators.rsi is not None
    assert indicators.rsi.period == 7
    assert isinstance(indicators.rsi.value, float)

    assert indicators.macd is not None
    assert indicators.macd.fast == 5
    assert indicators.macd.slow == 10
    assert indicators.macd.signal_period == 4
    assert isinstance(indicators.macd.histogram, float)

    assert indicators.ma is not None
    assert set(indicators.ma.price_ma) == {3, 5, 8}
    assert set(indicators.ma.volume_ma) == {3}

    assert indicators.bollinger is not None
    assert indicators.bollinger.period == 10

    assert indicators.stochastic is not None
    assert indicators.stochastic.k_period == 5
    assert indicators.stochastic.d_period == 3

    assert indicators.adx is not None
    assert indicators.adx.period == 7

    assert indicators.atr is not None
    assert indicators.atr.period == 7

    assert indicators.obv is not None
    assert indicators.obv.ma_period == 5

    assert indicators.mfi is not None
    assert indicators.mfi.period == 7


def test_calculator_omits_indicators_without_enough_history() -> None:
    parameters = IndicatorParameters(rsi_period=14, macd_fast=12, macd_slow=26, macd_signal=9)

    indicators = TechnicalIndicatorCalculator(parameters).calculate(_sample_bars(5))

    assert indicators.rsi is None
    assert indicators.macd is None


def _sample_bars(count: int) -> list[Ohlcv]:
    start = datetime(2026, 1, 1)
    bars: list[Ohlcv] = []

    for index in range(count):
        close = 100 + index + ((index % 3) * 0.5)
        bars.append(
            Ohlcv(
                ts=start + timedelta(days=index),
                open=close - 0.8,
                high=close + 1.5,
                low=close - 1.2,
                close=close,
                volume=1_000 + (index * 20),
            )
        )

    return bars
