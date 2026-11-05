from datetime import datetime

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from a_domain.types.enums import ExecutionProvider, OrderMode, Workflow
from a_domain.types.ids import RunId, new_run_id
from a_domain.types.values import FormulaId


@dataclass(config=ConfigDict(validate_assignment=True), kw_only=True)
class SystemStats:
    """
    One workflow run: its identity, the trading settings, technical strategy and AI model it ran with, timing,
    counters and errors. Saved as the run record when the run starts and again when it finishes; an empty end_time
    means the run never finished.

    `run_id` is the single run identity: every signal saved, order sent and snapshot taken during the run carries it.
    """

    run_id: RunId = Field(default_factory=new_run_id)
    workflow: Workflow
    execution_provider: ExecutionProvider
    order_mode: OrderMode
    start_time: datetime
    end_time: datetime | None = None

    technical_strategy_id: FormulaId | None = None
    """The technical strategy the run applied. None until TechnicalFilter applies one."""

    ai_model: str | None = None
    """The configured model of the active AI provider. None when the provider has no model configured, and on a read-only step."""

    total_scanned: int = 0

    buzz_scanned: int = 0
    buzz_qualified: int = 0
    sentiment_analysed: int = 0
    """Buzz stocks whose social sentiment was tallied."""

    passed_technical: int = 0
    ai_analysed: int = 0
    signals_generated: int = 0
    orders_submitted: int = 0
    orders_filled: int = 0
    """Orders that filled in full or in part."""

    orders_refused: int = 0
    stale_market_data_count: int = 0

    errors: list[str] = Field(default_factory=list)
    execution_log: list[str] = Field(default_factory=list)

    failure: str | None = None
    """
    The exception that stopped the run before its last step, as "<type>: <message>". None while the run goes on and
    when it ran every step; a run with a failure still has an end_time.
    """

    @property
    def total_errors(self) -> int:
        return len(self.errors)

    def finish(self, *, now: datetime) -> None:
        self.end_time = now

    def log(self, message: str, *, now: datetime) -> None:
        self.execution_log.append(f"[{now:%H:%M:%S}] {message}")

    def add_error(self, error: str) -> str:
        """Records an error of the run and returns it, so the caller can log the same text."""
        self.errors.append(error)

        return error
