from typing import Protocol

from backend.src.a_domain.model.indicators.technical_indicators import TechnicalIndicators
from backend.src.a_domain.model.market.ohlcv import Ohlcv


class IIndicatorProvider(Protocol):
    def calculate_indicators(self, data: list[Ohlcv]) -> TechnicalIndicators: ...
