from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class SystemStats:
    id: UUID = field(default_factory=uuid4)
    start_time: datetime = field(default_factory=datetime.now)
    total_candidates: int = 0
    passed_technical: int = 0
    ai_analyzed: int = 0
    signals_generated: int = 0
    orders_submitted: int = 0
    errors: list[str] = field(default_factory=list)
    execution_log: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return (datetime.now() - self.start_time).total_seconds()

    def log(self, message: str):
        self.execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def add_error(self, error: str):
        self.errors.append(error)
