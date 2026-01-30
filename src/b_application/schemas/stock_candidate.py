from dataclasses import dataclass

from src.a_domain.model.market.stock import Stock
from src.a_domain.types.enums import CandidateSource


@dataclass
class StockCandidate:
    stock: Stock
    source: CandidateSource  # Enum: For Logic (Strict/Loose)
    trigger_note: str  # String: For Humans (e.g., "PTT爆文")
