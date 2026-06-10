from dataclasses import dataclass

import icontract


@icontract.invariant(lambda self: self.rsi_period > 0)
@icontract.invariant(lambda self: 0 < self.macd_fast < self.macd_slow)
@icontract.invariant(lambda self: self.macd_signal > 0)
@icontract.invariant(lambda self: 0 < self.ma_short < self.ma_mid < self.ma_long)
@icontract.invariant(lambda self: self.bb_period > 0)
@icontract.invariant(lambda self: self.bb_std > 0)
@icontract.invariant(lambda self: self.stoch_k > 0)
@icontract.invariant(lambda self: self.stoch_d > 0)
@icontract.invariant(lambda self: self.adx_period > 0)
@icontract.invariant(lambda self: self.atr_period > 0)
@icontract.invariant(lambda self: self.mfi_period > 0)
@dataclass(frozen=True)
class IndicatorParameters:
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    ma_short: int = 5
    ma_mid: int = 20
    ma_long: int = 60
    bb_period: int = 20
    bb_std: float = 2.0
    stoch_k: int = 9
    stoch_d: int = 3
    adx_period: int = 14
    atr_period: int = 14
    mfi_period: int = 14
