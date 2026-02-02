from typing import Protocol

from src.a_domain.model.indicators.technical_indicators import TechnicalIndicators
from src.a_domain.model.market.ohlcv import Ohlcv


class ITechnicalAnalysisProvider(Protocol):
    """
    Interface for the Calculation Engine.
    """

    def calculate_indicators(self, data: list[Ohlcv]) -> TechnicalIndicators:
        """
        Computes standard technical indicators from raw OHLCV data.
        Returns the aggregated TechnicalIndicators object.
        """
        ...
