"""
Technical Indicators Domain Models.

Value objects holding calculated indicator values.

If an indicator object exists, its calculated values are present. Missing or
insufficient history is represented by omitting the indicator object from
TechnicalIndicators.
"""

from dataclasses import dataclass

from a_domain.model.indicators.adx import Adx
from a_domain.model.indicators.atr import Atr
from a_domain.model.indicators.bollinger_bands import BollingerBands
from a_domain.model.indicators.macd import Macd
from a_domain.model.indicators.mfi import Mfi
from a_domain.model.indicators.moving_averages import MovingAverages
from a_domain.model.indicators.obv import Obv
from a_domain.model.indicators.rsi import Rsi
from a_domain.model.indicators.stochastic import Stochastic


@dataclass(frozen=True)
class TechnicalIndicators:
    rsi: Rsi | None = None
    macd: Macd | None = None
    ma: MovingAverages | None = None
    bollinger: BollingerBands | None = None
    stochastic: Stochastic | None = None
    adx: Adx | None = None
    atr: Atr | None = None
    obv: Obv | None = None
    mfi: Mfi | None = None
