from __future__ import annotations

from dataclasses import dataclass

from a_domain.model.valuation.valuation_report import ValuationReport
from a_domain.types.enums import EliminationReason


@dataclass(frozen=True)
class ScanElimination:
    report: ValuationReport
    reason: EliminationReason
    detail: str
