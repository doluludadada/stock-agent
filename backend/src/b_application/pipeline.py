# backend/src/b_application/pipeline.py

from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import AiAnalysisFocus, WatchlistType
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.schemas.technical_strategies import TechnicalStrategies
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.collect.market_scanner import MarketScanner
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.composite_scorer import CompositeScorer
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.use_cases.trade.watch_stocks import WatchStocks


class Pipeline:
    """
    Exposes the stock-trading operations used by CLI, API and schedulers.

    Each public method represents one complete application operation.
    """

    def __init__(
        self,
        account_loader: AccountLoader,
        account_risk_check: AccountRiskCheck,
        market_scanner: MarketScanner,
        data_collector: MarketDataCollector,
        buzz_scanner: BuzzScanner,
        news: NewsFeed,
        ai: AiAnalyser,
        technical_filter: TechnicalFilter,
        technical_strategies: TechnicalStrategies,
        composite_scorer: CompositeScorer,
        watch_stocks: WatchStocks,
        signals: Signals,
        order_execution: OrderExecution,
        reporting: Reporting,
        logger: ILoggingProvider,
    ) -> None:
        self._account_loader = account_loader
        self._account_risk_check = account_risk_check
        self._market_scanner = market_scanner
        self._data_collector = data_collector
        self._buzz_scanner = buzz_scanner
        self._news = news
        self._ai = ai
        self._technical_filter = technical_filter
        self._technical_strategies = technical_strategies
        self._composite_scorer = composite_scorer
        self._watch_stocks = watch_stocks
        self._signals = signals
        self._order_execution = order_execution
        self._reporting = reporting
        self._logger = logger

    async def run_full_cycle(self) -> PipelineStatus:
        """After-market full-universe analysis."""
        status = PipelineStatus()
        strategy_name = self._technical_strategies.active_name.value
        self._logger.info(f"Starting full market cycle. Strategy={strategy_name}.")

        await self._account_loader.execute(status)
        await self._account_risk_check.execute(status)
        await self._market_scanner.execute(status)
        await self._data_collector.execute(status.universe_stocks, status)
        status.survivors = await self._technical_filter.execute(status.universe_stocks, status, self._technical_strategies.active)
        await self._news.execute(status.survivors, status)
        await self._ai.execute(status.survivors, status, AiAnalysisFocus.FUNDAMENTAL)
        self._composite_scorer.execute(status.survivors)
        status.watchlist = await self._watch_stocks.execute(status.survivors, WatchlistType.TECHNICAL)

        await self._signals.execute(status.watchlist, status)
        await self._reporting.execute(status)
        status.stats.finish()

        self._logger.info(
            f"Full market cycle completed. "
            f"Scanned={status.stats.total_scanned}, "
            f"Survivors={len(status.survivors)}, "
            f"Signals={status.stats.signals_generated}."
        )

        # NOTE: Full Cycle currently runs after market close,
        # so it never submits orders.
        return status

    async def run_buzz_scan(self) -> PipelineStatus:
        """US-006: Runs short-term social momentum analysis."""
        status = PipelineStatus()
        self._logger.info("Starting social buzz cycle. Strategy=buzz, AI focus=momentum.")

        await self._account_loader.execute(status)
        await self._account_risk_check.execute(status)
        await self._buzz_scanner.execute(status)
        status.stats.total_scanned = len(status.buzz_stocks)

        if not status.buzz_stocks:
            await self._reporting.execute(status)
            status.stats.finish()
            self._logger.info("Social buzz cycle completed. No buzz candidates found.")
            return status

        await self._data_collector.execute(status.buzz_stocks, status)
        status.survivors = await self._technical_filter.execute(
            status.buzz_stocks,
            status,
            self._technical_strategies.buzz,
        )
        status.watchlist = await self._watch_stocks.execute(status.survivors, WatchlistType.BUZZ)
        await self._news.execute(status.survivors, status)
        await self._ai.execute(status.survivors, status, AiAnalysisFocus.MOMENTUM)
        self._composite_scorer.execute(status.survivors)
        await self._signals.execute(status.watchlist, status)
        await self._order_execution.execute(status.signals, status)
        await self._reporting.execute(status)
        status.stats.finish()

        self._logger.info(
            f"Social buzz cycle completed. "
            f"Candidates={len(status.buzz_stocks)}, "
            f"Qualified={len(status.survivors)}, "
            f"Orders={status.stats.orders_submitted}."
        )
        return status

    async def run_intraday(self) -> PipelineStatus:
        """Revalidates the active watchlist before permitted order submission."""
        # Intraday is an independent operation and owns its PipelineStatus.
        status = PipelineStatus()
        self._logger.info("Starting intraday watchlist cycle.")

        await self._account_loader.execute(status)
        await self._account_risk_check.execute(status)
        status.watchlist = await self._market_scanner.load_active_watchlist(status)

        watched_stocks = status.watchlist.willing_stocks
        status.stats.total_scanned = len(watched_stocks)

        if not watched_stocks:
            await self._order_execution.execute(status.signals, status)
            await self._reporting.execute(status)
            status.stats.finish()
            self._logger.info("Intraday cycle completed. Active watchlist is empty.")
            return status

        await self._data_collector.execute(watched_stocks, status)

        status.survivors = await self._technical_filter.execute(watched_stocks, status, self._technical_strategies.active)

        await self._news.execute(status.survivors, status)
        await self._ai.execute(status.survivors, status, AiAnalysisFocus.FUNDAMENTAL)
        self._composite_scorer.execute(status.survivors)

        decision_watchlist = StockWatchlist(willing_stocks=status.survivors)

        await self._signals.execute(decision_watchlist, status)
        await self._order_execution.execute(status.signals, status)
        await self._reporting.execute(status)

        status.stats.finish()
        self._logger.info("Intraday watchlist cycle completed.")
        return status

    async def analyse_specific_stocks(self, stock_ids: list[str]) -> PipelineStatus:
        """Produces complete reports for explicitly requested stocks."""
        self._logger.info(f"Starting specific-stock analysis: {stock_ids}")
        status = PipelineStatus()

        status.manual_stocks = await self._market_scanner.find_stocks_by_ids(stock_ids, status)

        if not status.manual_stocks:
            status.stats.finish()
            self._logger.info("Specific-stock analysis completed. No requested stocks were loaded.")
            return status

        await self._data_collector.execute(status.manual_stocks, status)
        status.survivors = await self._technical_filter.execute(status.manual_stocks, status, self._technical_strategies.active)

        # Human override:
        # Technical failure does not stop News, AI, or reporting.
        await self._news.execute(status.manual_stocks, status)
        await self._ai.execute(status.manual_stocks, status, AiAnalysisFocus.FUNDAMENTAL)
        self._composite_scorer.execute(status.manual_stocks)
        await self._reporting.execute(status)

        # NOTE:
        # Manual watchlist persistence belongs to CLI after confirmation.
        # Technical failure does not block MANUAL watchlist membership.
        status.stats.finish()

        self._logger.info(f"Specific-stock analysis completed. Analysed={len(status.manual_stocks)}.")
        return status
