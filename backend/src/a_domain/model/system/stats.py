from datetime import datetime

from sqlmodel import Field, SQLModel

from a_domain.types.enums import ExecutionProvider, OrderMode, Workflow
from a_domain.types.ids import RunId, new_run_id


class SystemStats(SQLModel):
    """
    One workflow run: its identity, the trading settings it ran with, timing, counters and errors.
    Saved as the run record when the run starts and again when it finishes; an empty end_time means
    the run never finished.

    `run_id` is the single run identity: every signal saved, order sent and snapshot taken during the run carries it.
    """

    run_id: RunId = Field(default_factory=new_run_id)
    workflow: Workflow
    execution_provider: ExecutionProvider
    order_mode: OrderMode
    start_time: datetime
    end_time: datetime | None = None

    total_scanned: int = 0

    buzz_scanned: int = 0
    buzz_qualified: int = 0

    passed_technical: int = 0
    ai_analysed: int = 0
    signals_generated: int = 0
    orders_submitted: int = 0
    orders_refused: int = 0
    stale_market_data_count: int = 0

    errors: list[str] = Field(default_factory=list)
    execution_log: list[str] = Field(default_factory=list)

    @property
    def total_errors(self) -> int:
        return len(self.errors)

    def finish(self, *, now: datetime) -> None:
        self.end_time = now

    def log(self, message: str, *, now: datetime) -> None:
        self.execution_log.append(f"[{now:%H:%M:%S}] {message}")

    def add_error(self, error: str) -> None:
        self.errors.append(error)
