from datetime import date, datetime

from pydantic import ConfigDict, Field, NonNegativeInt
from pydantic.dataclasses import dataclass

from a_domain.model.trading.ranking_formula import RankingFormula
from a_domain.types.enums import ExecutionProvider, Workflow
from a_domain.types.ids import RunId, new_run_id
from a_domain.types.values import FormulaId


@dataclass(config=ConfigDict(validate_assignment=True), kw_only=True)
class SystemStats:
    """
    One workflow run: its identity, the broker it chose, the technical strategy and AI model it ran with, timing,
    counters and errors. Saved as the run record when the run starts and again when it finishes; an empty end_time
    means the run never finished.

    `run_id` is the single run identity: every signal saved, order sent and snapshot taken during the run carries it.
    """

    run_id: RunId = Field(default_factory=new_run_id)
    workflow: Workflow
    execution_provider: ExecutionProvider = Field(frozen=True)
    """
    The broker the run chose when it started, the mock account unless an administrator chose a real one. Every order of
    the run goes to it or is refused (BrokerAccessRule), and it never changes during the run.
    """

    start_time: datetime
    end_time: datetime | None = None

    followed_run_id: RunId | None = None
    """A follow's run: the run whose decisions it followed. None for every other workflow."""

    technical_strategy_id: FormulaId | None = None
    """The technical strategy the run applied. None until TechnicalFilter applies one."""

    ranking_formula: RankingFormula | None = None
    """
    The formula whose ranking a ranking follow brought the mock account to, as the settings defined it then, so its
    orders are never credited to a formula chosen later. None for every other workflow, and until the follow takes
    the decision.
    """

    ranking_decided_on: date | None = None
    """
    The decision session of the ranking a ranking follow took: it decided what to trade for it, or found the account
    held it already. None while its window refused it, so the decision is still to follow, and for every other workflow.
    """

    ranking_open: NonNegativeInt | None = None
    """
    How many stocks a ranking follow still had to trade when it last looked at the mock account: before its orders,
    and again after them. 0: the account holds the ranking, so the follow finished the decision. More: an order was
    refused or did not fill, a stock got no decision, or the run stopped before its last look. None for a ranking
    that decides nothing, and for every other workflow.
    """

    scheduled: bool = False
    """The site's own schedule started the run, not a user's request."""

    ai_model: str | None = None
    """
    The model id of the AI model the run used: its user's choice while the site offers it, else ai.active_model's. None
    when the provider has no model configured, and on a read-only step.
    """

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
