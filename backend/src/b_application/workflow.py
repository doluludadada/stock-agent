from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import WatchlistType
from b_application.schemas.pipeline_context import PipelineContext
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.market_data import MarketData
from b_application.use_cases.collect.market_scanner import MarketScanner
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.collect.stock_selector import StockSelector
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.order_execution import OrderExecution


class WorkflowOrchestrator:
    """Coordinates independent Use Cases to accomplish the 4 CLI operations."""

    def __init__(
        self,
        market_scanner: MarketScanner,
        buzz_scanner: BuzzScanner,
        account_loader: AccountLoader,
        account_risk_check: AccountRiskCheck,
        stock_selector: StockSelector,
        market_data: MarketData,
        technical_filter: TechnicalFilter,
        news_feed: NewsFeed,
        ai_analyser: AiAnalyser,
        signals: Signals,
        order_execution: OrderExecution,
        reporting: Reporting,
        watchlist_repo: IWatchlistRepository,
        logger: ILoggingProvider,
        db=None,
    ):
        self._market_scanner = market_scanner
        self._buzz_scanner = buzz_scanner
        self._account_loader = account_loader
        self._account_risk_check = account_risk_check
        self._stock_selector = stock_selector
        self._market_data = market_data
        self._technical_filter = technical_filter
        self._news_feed = news_feed
        self._ai_analyser = ai_analyser
        self._signals = signals
        self._order_execution = order_execution
        self._reporting = reporting
        self._watchlist_repo = watchlist_repo
        self._logger = logger
        self._db = db

    async def shutdown(self) -> None:
        if self._db:
            await self._db.close()

    # ----------------------------------------------------------------------
    # [1] Run Full Cycle (Nightly Scan) - Build Watchlist, Analyze, No Orders
    # ----------------------------------------------------------------------
    async def run_full_cycle(self) -> PipelineContext:
        ctx = PipelineContext()
        self._logger.info("=== Starting Full Market Scan ===")

        await self._market_scanner.execute(ctx)
        if ctx.target_stocks:
            await self._market_data.execute(ctx)
            await self._technical_filter.execute(ctx)

        if ctx.target_stocks:
            entries = [StockWatchlist(stock_id=s.stock_id, type=WatchlistType.TECHNICAL) for s in ctx.target_stocks]
            await self._watchlist_repo.upsert(entries)

            await self._news_feed.execute(ctx)
            await self._ai_analyser.execute(ctx)
            await self._signals.execute(ctx)

        ctx.stats.finish()
        return ctx

    # ----------------------------------------------------------------------
    # [2] Scan Social Buzz
    # ----------------------------------------------------------------------
    async def run_buzz_scan(self) -> PipelineContext:
        ctx = PipelineContext()
        self._logger.info("=== Starting Social Buzz Scan ===")

        # Scrapes & saves to Watchlist DB directly
        await self._buzz_scanner.execute()

        # Load from DB, analyse, execute mock
        await self._stock_selector.load_from_watchlist(ctx, WatchlistType.BUZZ)
        if ctx.target_stocks:
            await self._account_loader.execute(ctx)
            await self._market_data.execute(ctx)
            await self._technical_filter.execute(ctx)
            await self._news_feed.execute(ctx)
            await self._ai_analyser.execute(ctx)
            await self._signals.execute(ctx)
            await self._order_execution.execute(ctx)
            await self._reporting.execute(ctx)

        ctx.stats.finish()
        return ctx

    # ----------------------------------------------------------------------
    # [3] Run Intraday Trading
    # ----------------------------------------------------------------------
    async def run_intraday(self) -> PipelineContext:
        ctx = PipelineContext()
        self._logger.info("=== Starting Intraday Trading ===")

        await self._account_loader.execute(ctx)
        await self._account_risk_check.execute(ctx)

        await self._stock_selector.load_from_watchlist(ctx)  # Loads ALL active watchlist stocks

        if ctx.target_stocks or ctx.held_stocks:
            await self._market_data.execute(ctx)
            await self._technical_filter.execute(ctx)
            await self._news_feed.execute(ctx)
            await self._ai_analyser.execute(ctx)
            await self._signals.execute(ctx)
            await self._order_execution.execute(ctx)
            await self._reporting.execute(ctx)

        ctx.stats.finish()
        return ctx

    # ----------------------------------------------------------------------
    # [4] Analyse Specific Stocks
    # ----------------------------------------------------------------------
    async def analyze_specific_stocks(self, stock_ids: list[str]) -> PipelineContext:
        ctx = PipelineContext()
        self._logger.info(f"=== Analyzing Specific Stocks: {stock_ids} ===")

        await self._account_loader.execute(ctx)
        await self._stock_selector.load_by_ids(ctx, stock_ids)

        if ctx.target_stocks:
            await self._market_data.execute(ctx)
            await self._technical_filter.execute(ctx)
            await self._news_feed.execute(ctx)
            await self._ai_analyser.execute(ctx)
            await self._signals.execute(ctx)

        ctx.stats.finish()
        return ctx
