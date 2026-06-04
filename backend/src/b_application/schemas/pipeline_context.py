# backend/src/b_application/schemas/pipeline_context.py

from dataclasses import dataclass, field

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal


@dataclass
class PipelineContext:
    """
    Pipeline Context.

    This object is the mutable application workflow state.
    Each use case reads completed upstream fields and writes its own output fields.

    Workflow:
    Phase 1 Nightly:
        all_stocks -> technical_watchlist

    Phase 2 Morning:
        social/news scan -> buzz_watchlist

    Phase 3 Intraday:
        candidates -> priced -> survivors -> analysed -> buy/exit/hold signals -> orders/reporting
    """

    manual_symbols: list[str] = field(default_factory=list)
    """
    User-provided stock IDs.
    - These bypass the nightly/social candidate discovery flow and are merged by StockSelector.
    """

    account: Account = field(default_factory=Account)
    """
    Current broker/account state.
    - AccountLoader writes this before any decision logic runs.
    """

    positions_by_stock_id: dict[str, Position] = field(default_factory=dict)
    """
    Fast lookup table for held positions.
    - Signals uses this to decide whether a stock should go through EntryRule or ExitRule.
    """

    held_candidates: list[Stock] = field(default_factory=list)
    """
    Existing positions converted back into Stock analysis contexts.
    - Held stocks must enter the full funnel so the system can generate SELL or HOLD decisions.
    """

    all_stocks: list[Stock] = field(default_factory=list)
    """
    Full stock universe loaded during the nightly watchlist phase.
    """

    technical_watchlist: list[Stock] = field(default_factory=list)
    """
    Stocks that passed the nightly technical scan.
    - StockSelector merges these into intraday candidates.
    """

    buzz_watchlist: list[Stock] = field(default_factory=list)
    """
    Stocks discovered from social/news buzz.
    - StockSelector merges these into intraday candidates.
    """

    candidates: list[Stock] = field(default_factory=list)
    """
    Unified candidate list after merging technical, buzz, manual, and held candidates.
    """

    priced: list[Stock] = field(default_factory=list)
    """
    Candidates enriched with fresh realtime and historical OHLCV data.
    """

    survivors: list[Stock] = field(default_factory=list)
    """
    Stocks that continue after technical filtering.

    - Important:
        - For new candidates, this means they passed the technical filter.
        - For held positions, this also includes failed technical cases because failed held positions still need SELL/HOLD decisions.
    """

    analysed: list[Stock] = field(default_factory=list)
    """
    Stocks enriched with news, AI analysis, sentiment score, and final combined score input.
    """

    buy_signals: list[TradeSignal] = field(default_factory=list)
    """
    - Final BUY decisions.
    - OrderExecution consumes this list.
    - Reporting may notify this list.
    """

    exit_signals: list[TradeSignal] = field(default_factory=list)
    """
    Final SELL decisions.
    - OrderExecution consumes this list before BUY signals.
    - Reporting may notify this list.
    """

    hold_signals: list[TradeSignal] = field(default_factory=list)
    """
    Final HOLD decisions.
    - These are persisted for audit/RAG memory but should not become broker orders.
    """

    emergency_exit_signals: list[TradeSignal] = field(default_factory=list)
    risk_blocked_stock_ids: set[str] = field(default_factory=set)

    stats: SystemStats = field(default_factory=SystemStats)
    """
    Runtime counters, errors, execution log, and order submission count.
    """
