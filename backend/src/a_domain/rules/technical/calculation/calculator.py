from collections.abc import Sequence

from a_domain.model.indicators.technical_indicators import (
    Adx,
    Atr,
    BollingerBands,
    Macd,
    Mfi,
    MovingAverages,
    Obv,
    Rsi,
    Stochastic,
    TechnicalIndicators,
)
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
from a_domain.rules.technical.calculation.parameters import IndicatorParameters


class TechnicalIndicatorCalculator:
    def __init__(self, indicators: IndicatorParameters):
        self._indicators = indicators

    def calculate(self, data: Sequence[Ohlcv]) -> TechnicalIndicators:
        bars = sorted(data, key=lambda bar: bar.ts)
        if not bars:
            return TechnicalIndicators()

        indicators = self._indicators
        closes = [bar.close for bar in bars]
        volumes = [float(bar.volume) for bar in bars]

        rsi_value = latest_rsi(closes, indicators.rsi_period)
        macd_values = latest_macd(
            closes,
            indicators.macd_fast,
            indicators.macd_slow,
            indicators.macd_signal,
        )
        bollinger_values = latest_bollinger(closes, indicators.bb_period, indicators.bb_std)
        stochastic_values = latest_stochastic(bars, indicators.stoch_k, indicators.stoch_d)
        adx_values = latest_adx(bars, indicators.adx_period)
        atr_value = latest_atr(bars, indicators.atr_period)
        obv_values = latest_obv(closes, volumes, indicators.ma_mid)
        mfi_value = latest_mfi(bars, indicators.mfi_period)

        ma = self._calculate_moving_averages(closes, volumes)

        return TechnicalIndicators(
            rsi=Rsi(period=indicators.rsi_period, value=rsi_value) if rsi_value is not None else None,
            macd=self._create_macd(macd_values),
            ma=ma,
            bollinger=self._create_bollinger(bollinger_values),
            stochastic=self._create_stochastic(stochastic_values),
            adx=self._create_adx(adx_values),
            atr=self._create_atr(atr_value, closes[-1]),
            obv=self._create_obv(obv_values),
            mfi=Mfi(period=indicators.mfi_period, value=mfi_value) if mfi_value is not None else None,
        )

    def _calculate_moving_averages(
        self,
        closes: Sequence[float],
        volumes: Sequence[float],
    ) -> MovingAverages | None:
        indicators = self._indicators
        price_ma = {
            period: value
            for period in sorted({indicators.ma_short, indicators.ma_mid, indicators.ma_long})
            if (value := latest_sma(closes, period)) is not None and value > 0
        }

        volume_ma_value = latest_sma(volumes, indicators.ma_short)
        volume_ma = {indicators.ma_short: volume_ma_value} if volume_ma_value is not None and volume_ma_value > 0 else {}

        if not price_ma and not volume_ma:
            return None

        return MovingAverages(price_ma=price_ma, volume_ma=volume_ma)

    def _create_macd(self, values: tuple[float, float, float] | None) -> Macd | None:
        if values is None:
            return None

        line, signal, histogram = values
        indicators = self._indicators
        return Macd(
            fast=indicators.macd_fast,
            slow=indicators.macd_slow,
            signal_period=indicators.macd_signal,
            line=line,
            signal=signal,
            histogram=histogram,
        )

    def _create_bollinger(
        self,
        values: tuple[float, float, float, float, float] | None,
    ) -> BollingerBands | None:
        if values is None:
            return None

        upper, middle, lower, bandwidth, percent_b = values
        indicators = self._indicators
        return BollingerBands(
            period=indicators.bb_period,
            std=indicators.bb_std,
            upper=upper,
            middle=middle,
            lower=lower,
            bandwidth=bandwidth,
            percent_b=percent_b,
        )

    def _create_stochastic(self, values: tuple[float, float] | None) -> Stochastic | None:
        if values is None:
            return None

        k, d = values
        indicators = self._indicators
        return Stochastic(
            k_period=indicators.stoch_k,
            d_period=indicators.stoch_d,
            k=k,
            d=d,
        )

    def _create_adx(self, values: tuple[float, float, float] | None) -> Adx | None:
        if values is None:
            return None

        adx, plus_di, minus_di = values
        return Adx(
            period=self._indicators.adx_period,
            adx=adx,
            plus_di=plus_di,
            minus_di=minus_di,
        )

    def _create_atr(self, value: float | None, latest_close: float) -> Atr | None:
        if value is None or latest_close <= 0:
            return None

        return Atr(
            period=self._indicators.atr_period,
            value=value,
            percent=value / latest_close,
        )

    def _create_obv(self, values: tuple[float, float] | None) -> Obv | None:
        if values is None:
            return None

        value, moving_average = values
        return Obv(
            ma_period=self._indicators.ma_mid,
            value=value,
            moving_average=moving_average,
        )
