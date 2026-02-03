"""
Technical Indicators Domain Models.

These are value objects that hold calculated indicator values.
The calculation logic lives in the Infrastructure layer (ITechnicalAnalysisProvider).

References:
- Murphy, J. (1999). Technical Analysis of the Financial Markets. New York Institute of Finance.
- Elder, A. (1993). Trading for a Living. Wiley.
- Bollinger, J. (2001). Bollinger on Bollinger Bands. McGraw-Hill.
"""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Rsi:
    """
    Relative Strength Index (RSI).
    
    Interpretation (Wilder, 1978):
    - RSI > 70: Overbought (potential reversal down)
    - RSI < 30: Oversold (potential reversal up)
    - RSI 40-60: Neutral zone
    
    Reference:
    - Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
    """
    val_14: float | None  # Standard 14-period RSI
    val_7: float | None = None  # Short-term RSI for faster signals


@dataclass(frozen=True)
class Macd:
    """
    Moving Average Convergence Divergence (MACD).
    
    Standard Parameters (Appel, 1979):
    - Fast EMA: 12 periods
    - Slow EMA: 26 periods
    - Signal Line: 9-period EMA of MACD
    
    Interpretation:
    - MACD > Signal: Bullish momentum
    - MACD < Signal: Bearish momentum
    - Histogram increasing: Momentum strengthening
    
    Reference:
    - Appel, G. (2005). Technical Analysis: Power Tools for Active Investors.
    """
    line: float | None  # MACD Line (12 EMA - 26 EMA)
    signal: float | None  # Signal Line (9 EMA of MACD)
    histogram: float | None = None  # MACD - Signal


@dataclass(frozen=True)
class MovingAverages:
    """
    Moving Averages for trend identification.
    
    Common periods:
    - MA5/MA10: Short-term trend (traders)
    - MA20: Medium-term trend (swing traders)
    - MA60: Long-term trend (investors)
    - MA120/MA240: Very long-term trend
    
    Reference:
    - Murphy, J. (1999). Technical Analysis of the Financial Markets, Chapter 9.
    """
    ma_5: Decimal | None = None
    ma_10: Decimal | None = None
    ma_20: Decimal | None = None
    ma_60: Decimal | None = None
    ma_120: Decimal | None = None
    
    # Exponential Moving Averages (more weight to recent prices)
    ema_12: Decimal | None = None
    ema_26: Decimal | None = None
    
    # Volume Moving Average
    volume_ma_5: float | None = None
    volume_ma_20: float | None = None


@dataclass(frozen=True)
class BollingerBands:
    """
    Bollinger Bands for volatility measurement.
    
    Standard Parameters (Bollinger, 2001):
    - Middle Band: 20-period SMA
    - Upper Band: Middle + (2 × Standard Deviation)
    - Lower Band: Middle - (2 × Standard Deviation)
    
    Interpretation:
    - Price near upper band: Overbought / Strong uptrend
    - Price near lower band: Oversold / Strong downtrend
    - Band squeeze: Low volatility, breakout expected
    
    Reference:
    - Bollinger, J. (2001). Bollinger on Bollinger Bands. McGraw-Hill.
    """
    upper: Decimal | None
    middle: Decimal | None  # 20-period SMA
    lower: Decimal | None
    bandwidth: float | None = None  # (Upper - Lower) / Middle
    percent_b: float | None = None  # (Price - Lower) / (Upper - Lower)


@dataclass(frozen=True)
class Stochastic:
    """
    Stochastic Oscillator.
    
    Measures where price closed relative to the high-low range.
    
    Parameters:
    - %K: (Close - Lowest Low) / (Highest High - Lowest Low) × 100
    - %D: 3-period SMA of %K
    
    Interpretation (Lane, 1984):
    - %K > 80: Overbought
    - %K < 20: Oversold
    - %K crosses above %D: Buy signal
    - %K crosses below %D: Sell signal
    
    Reference:
    - Lane, G. (1984). Lane's Stochastics. Technical Analysis of Stocks & Commodities.
    """
    k: float | None  # Fast stochastic
    d: float | None  # Slow stochastic (signal line)


@dataclass(frozen=True)
class Adx:
    """
    Average Directional Index (ADX).
    
    Measures trend strength (not direction).
    
    Interpretation (Wilder, 1978):
    - ADX < 20: Weak trend or no trend (range-bound)
    - ADX 20-40: Developing trend
    - ADX > 40: Strong trend
    - ADX > 50: Very strong trend
    
    Reference:
    - Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
    """
    adx: float | None  # Average Directional Index
    plus_di: float | None  # +DI (bullish directional indicator)
    minus_di: float | None  # -DI (bearish directional indicator)


@dataclass(frozen=True)
class Atr:
    """
    Average True Range (ATR).
    
    Measures volatility (not direction).
    Used for position sizing and stop-loss placement.
    
    Interpretation:
    - High ATR: High volatility
    - Low ATR: Low volatility
    - Stop-loss typically set at 2-3 × ATR
    
    Reference:
    - Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
    """
    atr_14: float | None  # 14-period ATR
    atr_percent: float | None = None  # ATR as percentage of price


@dataclass(frozen=True)
class Obv:
    """
    On-Balance Volume (OBV).
    
    Cumulative volume indicator that adds volume on up days
    and subtracts volume on down days.
    
    Interpretation (Granville, 1963):
    - OBV rising with price: Confirms uptrend
    - OBV falling with price: Confirms downtrend
    - OBV diverging from price: Potential reversal
    
    Reference:
    - Granville, J. (1963). Granville's New Key to Stock Market Profits.
    """
    obv: float | None
    obv_ma_20: float | None = None  # 20-period MA of OBV for trend


@dataclass(frozen=True)
class Mfi:
    """
    Money Flow Index (MFI).
    
    Volume-weighted RSI. Measures buying/selling pressure.
    
    Interpretation:
    - MFI > 80: Overbought
    - MFI < 20: Oversold
    - Divergence with price: Potential reversal
    
    Reference:
    - Quong, G. & Soudack, A. (1989). Volume-Weighted RSI.
    """
    mfi_14: float | None


@dataclass(frozen=True)
class TechnicalIndicators:
    """
    Aggregated technical indicators for analysis.
    
    This is the complete set of indicators calculated for a stock.
    """
    rsi: Rsi | None = None
    macd: Macd | None = None
    ma: MovingAverages | None = None
    bollinger: BollingerBands | None = None
    stochastic: Stochastic | None = None
    adx: Adx | None = None
    atr: Atr | None = None
    obv: Obv | None = None
    mfi: Mfi | None = None


