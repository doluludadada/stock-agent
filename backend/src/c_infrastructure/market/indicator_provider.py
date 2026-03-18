import math

import pandas as pd
import pandas_ta  # noqa: F401

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
from a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from b_application.schemas.config import AppConfig


class IndicatorProvider(IIndicatorProvider):
    """
    Calculates technical indicators using pandas-ta.
    All parameters are dynamically injected from AppConfig.indicators.
    """

    def __init__(self, config: AppConfig):
        self._config = config

    def calculate_indicators(self, data: list[Ohlcv]) -> TechnicalIndicators:
        ind = self._config.indicators

        if len(data) < ind.ma_long:
            return TechnicalIndicators()

        df = pd.DataFrame(
            [
                {
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in data
            ]
        )

        df.ta.rsi(length=ind.rsi_period, append=True)
        df.ta.macd(fast=ind.macd_fast, slow=ind.macd_slow, signal=ind.macd_signal, append=True)
        df.ta.sma(length=ind.ma_short, append=True)
        df.ta.sma(length=ind.ma_mid, append=True)
        df.ta.sma(length=ind.ma_long, append=True)
        df.ta.sma(close="volume", length=ind.ma_short, prefix="VOL", append=True)
        df.ta.bbands(length=ind.bb_period, std=ind.bb_std, append=True)
        df.ta.stoch(k=ind.stoch_k, d=ind.stoch_d, append=True)
        df.ta.adx(length=ind.adx_period, append=True)
        df.ta.atr(length=ind.atr_period, append=True)
        df.ta.obv(append=True)
        df.ta.mfi(length=ind.mfi_period, append=True)

        latest = df.iloc[-1]

        def safe_float(val) -> float | None:
            if pd.isna(val) or math.isnan(val):
                return None
            return float(val)

        try:
            rsi = Rsi(val_14=safe_float(latest.get(f"RSI_{ind.rsi_period}")))

            macd_base = f"{ind.macd_fast}_{ind.macd_slow}_{ind.macd_signal}"
            macd = Macd(
                line=safe_float(latest.get(f"MACD_{macd_base}")),
                signal=safe_float(latest.get(f"MACDs_{macd_base}")),
                histogram=safe_float(latest.get(f"MACDh_{macd_base}")),
            )

            ma = MovingAverages(
                ma_5=safe_float(latest.get(f"SMA_{ind.ma_short}")),
                ma_20=safe_float(latest.get(f"SMA_{ind.ma_mid}")),
                ma_60=safe_float(latest.get(f"SMA_{ind.ma_long}")),
                volume_ma_5=safe_float(latest.get(f"VOL_SMA_{ind.ma_short}")),
            )

            bb_base = f"{ind.bb_period}_{float(ind.bb_std)}"
            bollinger = BollingerBands(
                lower=safe_float(latest.get(f"BBL_{bb_base}")),
                middle=safe_float(latest.get(f"BBM_{bb_base}")),
                upper=safe_float(latest.get(f"BBU_{bb_base}")),
                bandwidth=safe_float(latest.get(f"BBB_{bb_base}")),
                percent_b=safe_float(latest.get(f"BBP_{bb_base}")),
            )

            stoch = Stochastic(
                k=safe_float(latest.get(f"STOCHk_{ind.stoch_k}_{ind.stoch_d}_3")),
                d=safe_float(latest.get(f"STOCHd_{ind.stoch_k}_{ind.stoch_d}_3")),
            )

            adx = Adx(
                adx=safe_float(latest.get(f"ADX_{ind.adx_period}")),
                plus_di=safe_float(latest.get(f"DMP_{ind.adx_period}")),
                minus_di=safe_float(latest.get(f"DMN_{ind.adx_period}")),
            )

            atr_val = safe_float(latest.get(f"ATRr_{ind.atr_period}"))
            atr_pct = (atr_val / latest["close"]) if atr_val and latest["close"] else None
            atr = Atr(atr_14=atr_val, atr_percent=atr_pct)

            obv = Obv(obv=safe_float(latest.get("OBV")))
            mfi = Mfi(mfi_14=safe_float(latest.get(f"MFI_{ind.mfi_period}")))

            return TechnicalIndicators(
                rsi=rsi, macd=macd, ma=ma, bollinger=bollinger, stochastic=stoch, adx=adx, atr=atr, obv=obv, mfi=mfi
            )

        except Exception:
            return TechnicalIndicators()
