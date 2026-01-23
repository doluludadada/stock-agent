from typing import Protocol

from src.a_domain.model.analysis.technical_indicators import TechnicalIndicators
from src.a_domain.model.market.ohlcv import Ohlcv


class ITechnicalAnalysisPort(Protocol):
    """
    Interface for the 'Left Brain' Calculation Engine.
    Responsibility: Pure Math.
    Logic (e.g., 'Is RSI > 70?') belongs to Domain Services, not here.
    """

    def calculate_indicators(self, data: list[Ohlcv]) -> TechnicalIndicators:
        """
        Computes standard technical indicators from raw OHLCV data.
        """
        ...
