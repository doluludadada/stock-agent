from dataclasses import dataclass, field

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import StockWatchlist


@dataclass
class PipelineStatus:
    """
    Runtime state for one workflow run. RunHistory.open creates it; `stats` is the run record.
    A read-only valuation step gets one from valuation_status() instead, which is never recorded.
    """

    stats: SystemStats
    """
    The run's identity (run_id, workflow), timing, counters and errors.
    """

    account: Account = field(default_factory=Account)
    """
    Cash and positions from the execution provider: loaded at the start of the run, re-read after every fill.
    """

    universe_stocks: list[Stock] = field(default_factory=list)
    """
    Stocks loaded by a full-market scan.
    """

    held_stocks: list[Stock] = field(default_factory=list)
    """
    Stocks the account holds, loaded so that stop-loss and exit decisions can run on them.
    """

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

    risk_blocked_stock_ids: set[str] = field(default_factory=set)
    """
    Stocks AccountRiskCheck already decided to sell; no other signal is generated for them in this run.
    """

    stale_stock_ids: set[str] = field(default_factory=set)
    """
    Stocks whose latest realtime quote was missing or older than the realtime freshness limit when fetched.
    """

    watchlist: StockWatchlist = field(default_factory=StockWatchlist)
    """
    The watchlist this run trades from: technical or buzz survivors, or the active watchlist for intraday.
    """

    signals: list[TradeSignal] = field(default_factory=list)
    """
    Every decision made in this run, HOLD included.
    """

    orders: list[Order] = field(default_factory=list)
    """
    One order per orderable decision OrderExecution handled, sent or refused.
    """
