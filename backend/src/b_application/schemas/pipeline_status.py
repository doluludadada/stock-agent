from dataclasses import dataclass, field
from datetime import datetime
from typing import Self

from a_domain.model.analysis.social_sentiment import SocialSentiment
from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.stock_watchlist import StockWatchlist
from a_domain.types.enums import ExecutionProvider, OrderMode, Workflow


@dataclass
class PipelineStatus:
    """
    Runtime state for one workflow run. RunHistory.execute creates it; `stats` is the run record.
    A read-only valuation step gets one from for_valuation() instead, which is never recorded.
    """

    stats: SystemStats
    """
    The run's identity (run_id, workflow), timing, counters and errors.
    """

    account: Account = field(default_factory=Account)
    """
    Cash and positions from the execution provider: loaded at the start of the run, re-read after every fill.
    """

    equity: float | None = None
    """
    The account's cash plus each position at the run's latest price for it, fixed by AccountEquity before the run's
    first decision and kept for the whole run. Every BUY's risk budget is analysis.risk_per_trade_pct of it.
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
    Watchlist stocks of this run: the survivors that Full Cycle and Buzz add,
    or the active watchlist that Intraday loads.
    """

    sentiment_by_stock_id: dict[str, SocialSentiment] = field(default_factory=dict)
    """
    Buzz report only. Kept off Stock, which DecisionRule reads, and filled after orders are executed.
    """

    signals: list[TradeSignal] = field(default_factory=list)
    """
    Every decision made in this run, HOLD included.
    """

    orders: list[Order] = field(default_factory=list)
    """
    One order per orderable decision OrderExecution handled, sent or refused.
    """

    manual_buy_refusal: str | None = None
    """
    Why the confirmed manual BUY of this run sent no order. Unset when OrderExecution made its order.
    """

    @classmethod
    def for_valuation(cls, now: datetime) -> Self:
        """
        Collects one valuation step's counters and errors for the shared collect and process use cases.
        Valuation records no run and sends no order, so the run identity is fixed to values that cannot order.
        """
        return cls(
            stats=SystemStats(
                workflow=Workflow.VALUATION, execution_provider=ExecutionProvider.MOCK, order_mode=OrderMode.DISABLED, start_time=now
            )
        )

    def require_equity(self) -> float:
        """The run's equity. Raises when no AccountEquity step fixed it before a decision needed it."""
        if self.equity is None:
            raise RuntimeError("the run's equity was not fixed before its first decision")

        return self.equity

    def mark_stale(self, stock_id: str) -> None:
        """Adds the stock to stale_stock_ids. Each stock counts once toward stats.stale_market_data_count."""
        if stock_id not in self.stale_stock_ids:
            self.stats.stale_market_data_count += 1

        self.stale_stock_ids.add(stock_id)

    def require_manual_buy_order(self) -> Order:
        """The order OrderExecution made for an unrefused manual BUY. It raises when the run refused the BUY instead."""
        if self.manual_buy_refusal is not None or len(self.orders) != 1:
            raise ValueError(f"the manual BUY run has no single order: refusal={self.manual_buy_refusal!r}, orders={len(self.orders)}")

        return self.orders[0]
