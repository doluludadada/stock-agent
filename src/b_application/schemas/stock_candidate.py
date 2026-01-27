from dataclasses import dataclass

from src.a_domain.model.market.stock import Stock
from src.a_domain.types.enums import CandidateSource


@dataclass
class StockCandidate:
    stock: Stock
    source: CandidateSource
    trigger_reason: str
