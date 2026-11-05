from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Self

from a_domain.model.analysis.social_sentiment import SocialSentiment
from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account, AccountSnapshot
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.types.enums import ExecutionProvider, IndicatorOutput, OrderMode, Workflow
from a_domain.types.values import FormulaId


@dataclass
class PipelineStatus:
    """
    What the steps of one run returned. Only the Pipeline writes these fields: a use case gets the values it needs as
    arguments and adds only to `stats`. Each field's docstring names the step whose result the Pipeline stores there.

    Stock is an entity, so the steps that enrich stocks (history, indicators, reports, articles, quotes, scores)
    change the Stock objects these lists hold and return nothing. A list field says which stocks a step worked on.
    """

    stats: SystemStats
    """RunHistory yields it: the run's identity (run_id, workflow), timing, counters and errors."""

    account: Account = field(default_factory=Account)
    """
    AccountLoader, then OrderOutcome after every order: the broker re-read after a fill, so later decisions see it.
    Unmarked in every trading run. AccountHistory: the account valued at each position's latest price, menu 7's
    account now.
    """

    equity: float | None = None
    """
    AccountRiskCheck, once, before the run's first decision: the account's cash plus each position at the run's latest
    price for it, kept for the whole run. Every automatic BUY's risk budget is analysis.risk_per_trade_pct of it. A
    manual BUY's ManualSignal fixes its own equity and leaves this unset.
    """

    universe_stocks: list[Stock] = field(default_factory=list)
    """
    MarketScanner: every listed stock, for Full Cycle and the valuation workflows, and the names of the watched stocks.
    Empty during a listing outage.
    """

    watchlist: list[WatchlistEntry] = field(default_factory=list)
    """ActiveWatchlist: every active watchlist entry, one per stock and watchlist type."""

    held_stocks: list[Stock] = field(default_factory=list)
    """
    AccountLoader: one Stock per position, so that stop-loss and exit decisions can run on them. AccountHistory: the
    same, with the daily history and the realtime quote that value `account`.
    """

    buzz_stocks: list[Stock] = field(default_factory=list)
    """BuzzScanner: the stocks the social-buzz workflow found."""

    candidates: list[Stock] = field(default_factory=list)
    """IntradayCandidates: the held and the watched stocks, each once."""

    technical_candidates: list[Stock] = field(default_factory=list)
    """MarketDataCollector, where an operation screens only stocks with daily history: Intraday and menu 6."""

    manual_stocks: list[Stock] = field(default_factory=list)
    """
    StockLookup, or the stock buy_manually was given. They stay here whatever their technical verdict, so that
    specific-stock analysis goes on through news and AI.
    """

    survivors: list[Stock] = field(default_factory=list)
    """
    TechnicalFilter: the stocks that passed the strategy, which go on to analysis and decisions. In Intraday the held
    stocks that failed it follow them, so that each position still gets its exit decided.
    """

    risk_blocked_stock_ids: set[str] = field(default_factory=set)
    """AccountRiskCheck: each stock it decided to sell, its decision saved or not. No other decision is made for them."""

    stale_stock_ids: set[str] = field(default_factory=set)
    """RealtimeQuoteFeed, after each refresh: the stocks without a fresh quote. A later fresh quote takes a stock off."""

    sentiment_by_stock_id: dict[str, SocialSentiment] = field(default_factory=dict)
    """SentimentAnalyser: Buzz report only. Kept off Stock, which DecisionRule reads, and filled after the orders."""

    signals: list[TradeSignal] = field(default_factory=list)
    """AccountRiskCheck's stop-loss SELLs, then Signals' decisions, or ManualSignal's decision: every one recorded."""

    orders: list[Order] = field(default_factory=list)
    """The order step: one per orderable decision, sent or refused, as OrderExecution returned it."""

    manual_buy_refusal: str | None = None
    """ManualSignal: why the confirmed manual BUY of this run sent no order. Unset when it made an orderable decision."""

    indicator_readings: dict[FormulaId, list[dict[IndicatorOutput, float]]] = field(default_factory=dict)
    """IndicatorReadings: each indicator of `strategy` at every daily bar the stock page's evaluation read."""

    equity_curve: dict[date, Account] = field(default_factory=dict)
    """AccountHistory: the account at the end of each trading day since the first fill, in day order, at that day's closes."""

    account_as_of: AccountSnapshot | None = None
    """
    AccountHistory: the last fill on or before the asked day, its account valued at that day's closes. None when no day
    was asked or no fill came on or before it.
    """

    @property
    def live_stock_ids(self) -> frozenset[str]:
        """The held stocks that have a realtime quote. Every other position is at its last daily close, or unpriced."""
        return frozenset(stock.stock_id for stock in self.held_stocks if stock.realtime_bar is not None)

    @property
    def stocks(self) -> dict[str, Stock]:
        """
        Every stock the run loaded, by id, the first object per id. AccountLoader and BuzzScanner reuse a stock they
        find here; MarketScanner loads its own copies. Fill snapshots, the equity and decision memory read stocks
        through it. The full market comes first, so Full
        Cycle marks a held stock with the copy whose history it loaded.
        """
        lists = (self.universe_stocks, self.held_stocks, self.buzz_stocks, self.candidates, self.manual_stocks)
        stocks: dict[str, Stock] = {}

        for stock in (stock for stock_list in lists for stock in stock_list):
            stocks.setdefault(stock.stock_id, stock)

        return stocks

    @property
    def blocked_stock_ids(self) -> frozenset[str]:
        """The stocks this run may not act on any more: those the stop-loss check sold and those without a fresh quote."""
        return frozenset(self.risk_blocked_stock_ids | self.stale_stock_ids)

    @classmethod
    def read_only(cls, workflow: Workflow) -> Self:
        """
        The status of one read-only step (valuation, the stock page, the account history), for the counters and errors
        of the collect and process steps it shares with the trading workflows. It records no run and sends no order, so
        its run identity is fixed to values that cannot order, and its start time is the Unix epoch, which nothing
        reads. Its execution_provider and order_mode say that this step cannot order, never whose account it read.
        """
        stats = SystemStats(
            workflow=workflow,
            execution_provider=ExecutionProvider.MOCK,
            order_mode=OrderMode.DISABLED,
            start_time=datetime.fromtimestamp(0, UTC),
        )

        return cls(stats=stats)

    def require_equity(self) -> float:
        """The run's equity. Raises when no AccountRiskCheck fixed it before a decision needed it."""
        if self.equity is None:
            raise RuntimeError("the run's equity was not fixed before its first decision")

        return self.equity

    def require_manual_buy_order(self) -> Order:
        """The one order of an unrefused manual BUY. It raises when the run refused the BUY instead."""
        if self.manual_buy_refusal is not None or len(self.orders) != 1:
            raise ValueError(f"the manual BUY run has no single order: refusal={self.manual_buy_refusal!r}, orders={len(self.orders)}")

        return self.orders[0]
