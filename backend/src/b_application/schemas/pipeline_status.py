from dataclasses import dataclass, field

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account
from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import StockWatchlist


# TODO. Add comment for those variables.
@dataclass
class PipelineStatus:
    """
    Runtime state for one pipeline operation.
    """

    account: Account = field(default_factory=Account)

    universe_stocks: list[Stock] = field(default_factory=list)
    """
    Stocks loaded by a full-market scan.
    """

    held_stocks: list[Stock] = field(default_factory=list)

    buzz_stocks: list[Stock] = field(default_factory=list)
    """
    Stocks discovered from the social-buzz workflow.
    """

    manual_stocks: list[Stock] = field(default_factory=list)
    """
    Stocks explicitly requested by the user.

    Manual stocks remain here regardless of technical pass/fail so that
    specific-stock analysis can continue through News and AI.
    """

    survivors: list[Stock] = field(default_factory=list)
    """
    Stocks that passed the active technical strategy.

    Automatic workflows use survivors as the gate for expensive analysis
    and automatic trading decisions.
    """

    stocks_cache: dict[str, Stock] = field(default_factory=dict)
    """
    Runtime stock cache keyed by stock_id.
    """

    positions_by_stock_id: dict[str, Position] = field(default_factory=dict)
    risk_blocked_stock_ids: set[str] = field(default_factory=set)

    watchlist: StockWatchlist = field(default_factory=StockWatchlist)
    # The stock Buzz and techncial filter should be added to here

    signals: list[TradeSignal] = field(default_factory=list)

    orders: list[Order] = field(default_factory=list)
    stats: SystemStats = field(default_factory=SystemStats)
