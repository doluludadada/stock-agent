from dataclasses import dataclass, field

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import StockWatchlist


@dataclass
class PipelineContext:
    """
    Streamlined Pipeline Context.
    Passes linearly through specific Workflow Orchestrators.
    """

    account: Account = field(default_factory=Account)


    candidates: list[Stock] = field(default_factory=list)
    """
    universe stock (it should clean everytime runs pipeline)
    """

    survivors: list[Stock] = field(default_factory=list)
    """
    After techncial filter
    """

    watchlist: list[StockWatchlist] = field(default_factory=list)
    # The stock Buzz and techncial filter should be added to here


    buy_signals: list[TradeSignal] = field(default_factory=list)
    exit_signals: list[TradeSignal] = field(default_factory=list)
    hold_signals: list[TradeSignal] = field(default_factory=list)
    emergency_exit_signals: list[TradeSignal] = field(default_factory=list)

    stats: SystemStats = field(default_factory=SystemStats)
