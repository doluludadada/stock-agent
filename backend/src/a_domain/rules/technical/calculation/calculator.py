from collections.abc import Sequence

from a_domain.model.indicators.adx import Adx
from a_domain.model.indicators.atr import Atr
from a_domain.model.indicators.bollinger_bands import BollingerBands
from a_domain.model.indicators.indicator_parameters import IndicatorParameters
from a_domain.model.indicators.macd import Macd
from a_domain.model.indicators.mfi import Mfi
from a_domain.model.indicators.moving_averages import MovingAverages
from a_domain.model.indicators.obv import Obv
from a_domain.model.indicators.rsi import Rsi
from a_domain.model.indicators.stochastic import Stochastic
from a_domain.model.indicators.technical_indicators import TechnicalIndicators
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.rules.technical.calculation.formulas import (
    latest_adx,
    latest_atr,
    latest_bollinger,
    latest_macd,
    latest_mfi,
    latest_obv,
    latest_rsi,
    latest_sma,
    latest_stochastic,
)


class TechnicalIndicatorCalculator:
    def __init__(self, indicators: IndicatorParameters):
        self._indicators = indicators

    def apply(self, data: Sequence[Ohlcv]) -> TechnicalIndicators:
        bars = sorted(data, key=lambda bar: bar.ts)
        if not bars:
            return TechnicalIndicators()

        closes = [bar.close for bar in bars]
        volumes = [float(bar.volume) for bar in bars]

        return TechnicalIndicators(
            rsi=self._create_rsi(closes),
            macd=self._create_macd(closes),
            ma=self._create_moving_averages(closes, volumes),
            bollinger=self._create_bollinger(closes),
            stochastic=self._create_stochastic(bars),
            adx=self._create_adx(bars),
            atr=self._create_atr(bars, closes[-1]),
            obv=self._create_obv(closes, volumes),
            mfi=self._create_mfi(bars),
        )

    def _create_rsi(self, closes: Sequence[float]) -> Rsi | None:
        value = latest_rsi(closes, self._indicators.rsi_period)
        if value is None:
            return None

        return Rsi(period=self._indicators.rsi_period, value=value)

    def _create_moving_averages(self, closes: Sequence[float], volumes: Sequence[float]) -> MovingAverages | None:
        indicators = self._indicators
        price_ma = {
            period: value
            for period in sorted(indicators.price_ma_periods)
            if (value := latest_sma(closes, period)) is not None and value > 0
        }
        volume_ma = {
            period: value
            for period in sorted(indicators.volume_ma_periods)
            if (value := latest_sma(volumes, period)) is not None and value > 0
        }

        if not price_ma and not volume_ma:
            return None

        return MovingAverages(price_ma=price_ma, volume_ma=volume_ma)

    def _create_macd(self, closes: Sequence[float]) -> Macd | None:
        indicators = self._indicators
        values = latest_macd(closes, indicators.macd_fast, indicators.macd_slow, indicators.macd_signal)
        if values is None:
            return None

        line, signal, histogram = values
        return Macd(
            fast=indicators.macd_fast,
            slow=indicators.macd_slow,
            signal_period=indicators.macd_signal,
            line=line,
            signal=signal,
            histogram=histogram,
        )

    def _create_bollinger(self, closes: Sequence[float]) -> BollingerBands | None:
        indicators = self._indicators
        values = latest_bollinger(closes, indicators.bb_period, indicators.bb_std)
        if values is None:
            return None

        upper, middle, lower, bandwidth, percent_b = values
        return BollingerBands(
            period=indicators.bb_period,
            std=indicators.bb_std,
            upper=upper,
            middle=middle,
            lower=lower,
            bandwidth=bandwidth,
            percent_b=percent_b,
        )

    def _create_stochastic(self, bars: Sequence[Ohlcv]) -> Stochastic | None:
        indicators = self._indicators
        values = latest_stochastic(bars, indicators.stoch_k, indicators.stoch_d)
        if values is None:
            return None

        percent_k, percent_d = values
        return Stochastic(k_period=indicators.stoch_k, d_period=indicators.stoch_d, percent_k=percent_k, percent_d=percent_d)

    def _create_adx(self, bars: Sequence[Ohlcv]) -> Adx | None:
        values = latest_adx(bars, self._indicators.adx_period)
        if values is None:
            return None

        adx, plus_di, minus_di = values
        return Adx(period=self._indicators.adx_period, adx=adx, plus_di=plus_di, minus_di=minus_di)

    def _create_atr(self, bars: Sequence[Ohlcv], latest_close: float) -> Atr | None:
        value = latest_atr(bars, self._indicators.atr_period)
        if value is None or latest_close <= 0:
            return None

        return Atr(period=self._indicators.atr_period, value=value, percent=value / latest_close)

    def _create_obv(self, closes: Sequence[float], volumes: Sequence[float]) -> Obv | None:
        values = latest_obv(closes, volumes, self._indicators.ma_mid)
        if values is None:
            return None

        value, moving_average = values
        return Obv(ma_period=self._indicators.ma_mid, value=value, moving_average=moving_average)

    def _create_mfi(self, bars: Sequence[Ohlcv]) -> Mfi | None:
        value = latest_mfi(bars, self._indicators.mfi_period)
        if value is None:
            return None

        return Mfi(period=self._indicators.mfi_period, value=value)
