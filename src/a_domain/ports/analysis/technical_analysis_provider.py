from typing import Protocol, Tuple

from src.a_domain.model.indicators.macd import Macd
from src.a_domain.model.indicators.moving_averages import MovingAverages
from src.a_domain.model.indicators.rsi import Rsi
from src.a_domain.model.market.ohlcv import Ohlcv


class ITechnicalAnalysisProvider(Protocol):
    """
    Interface for the 'Left Brain' Calculation Engine.
    Responsibility: Pure Math.
    Logic (e.g., 'Is RSI > 70?') belongs to Domain Services, not here.
    """

    def calculate_indicators(self, data: list[Ohlcv]) -> Tuple[Rsi, Macd, MovingAverages]:
        """
        Computes standard technical indicators from raw OHLCV data.
        Returns explicit domain models for RSI, MACD, and Moving Averages.
        """
        ...
