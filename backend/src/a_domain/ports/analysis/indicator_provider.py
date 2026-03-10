from typing import Protocol

from a_domain.model.indicators.technical_indicators import TechnicalIndicators
from a_domain.model.market.ohlcv import Ohlcv


class IIndicatorProvider(Protocol):
    """Infrastructure adapter for calculating technical indicators (e.g. pandas-ta)."""

    def calculate_indicators(self, data: list[Ohlcv]) -> TechnicalIndicators: ...
