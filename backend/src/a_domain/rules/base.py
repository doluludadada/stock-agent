"""
Base Trading Rule Interface.

All trading rules must implement this interface.
Each rule answers ONE specific question about a StockCandidate.
"""
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from backend.src.a_domain.model.analysis.stock_candidate import StockCandidate


class TradingRule(Protocol):

    @property
    def name(self) -> str: ...

    def is_satisfied(self, candidate: "StockCandidate") -> bool: ...
