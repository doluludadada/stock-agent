from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class SystemStats(SQLModel):
    id: UUID = Field(default_factory=uuid4)
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: datetime | None = None
    total_scanned: int = 0
    total_skipped: int = 0
    total_filtered: int = 0
    passed_technical: int = 0
    ai_analysed: int = 0
    signals_generated: int = 0
    orders_submitted: int = 0
    errors: list[str] = Field(default_factory=list)
    execution_log: list[str] = Field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()

    @property
    def total_errors(self) -> int:
        return len(self.errors)

    def finish(self) -> None:
        self.end_time = datetime.now()

    def log(self, message: str) -> None:
        self.execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def add_error(self, error: str) -> None:
        self.errors.append(error)
