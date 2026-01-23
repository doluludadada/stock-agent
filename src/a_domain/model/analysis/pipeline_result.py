from dataclasses import dataclass, field
from datetime import datetime

from src.a_domain.model.analysis.signal import TradeSignal


@dataclass(frozen=True)
class PipelineResult:
    """
    Summary of a complete analysis pipeline execution.
    Immutable to ensure result integrity.
    """

    signals: tuple[TradeSignal, ...]
    total_scanned: int
    passed_screening: int
    execution_time_ms: int
    executed_at: datetime = field(default_factory=datetime.now)
    errors: tuple[str, ...] = field(default_factory=tuple)
