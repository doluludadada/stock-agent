from dataclasses import dataclass, field

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.signal import TradeSignal


@dataclass
class PipelineContext:
    """
    Pipeline Context.

    A mutable data bag that flows through the entire three-phase workflow.
    Each use case reads from upstream fields and writes to its own output fields.

    Phase 1 (Nightly):   universe → technical_watchlist
    Phase 2 (Morning):   social scan → buzz_watchlist
    Phase 3 (Intraday):  candidates → priced → survivors → analysed → signals → orders
    """

    # ---------------------------------- Input ----------------------------------- #
    manual_symbols: list[str] = field(default_factory=list)

    # ----------------------------- Phase 1 (Nightly) ---------------------------- #
    universe: list[Stock] = field(default_factory=list)
    technical_watchlist: list[Stock] = field(default_factory=list)

    # ----------------------------- Phase 2 (Morning) ---------------------------- #
    buzz_watchlist: list[Stock] = field(default_factory=list)

    # ----------------------- Phase 3 (Intraday — Buy Flow) ---------------------- #
    candidates: list[Stock] = field(default_factory=list)
    priced: list[Stock] = field(default_factory=list)
    survivors: list[Stock] = field(default_factory=list)
    analysed: list[Stock] = field(default_factory=list)
    buy_signals: list[TradeSignal] = field(default_factory=list)

    # ---------------------- Phase 3 (Intraday — Sell Flow) ---------------------- #
    exit_signals: list[TradeSignal] = field(default_factory=list)

    # ---------------------------------- Output ---------------------------------- #
    orders_submitted: int = 0

    # ----------------------------------- Stats ---------------------------------- #
    stats: SystemStats = field(default_factory=SystemStats)
