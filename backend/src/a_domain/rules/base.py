"""
Base Trading Rule Interface.

All trading rules must implement this interface.
Each rule answers ONE specific question about a Stock.
"""
from typing import Protocol

from backend.src.a_domain.model.market.stock import Stock


class TradingRule(Protocol):

    @property
    def name(self) -> str: ...

    def apply(self, stock: Stock) -> bool: ...
