from dataclasses import dataclass

from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import AiAnalysisFocus, WatchlistType
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.collect.market_scanner import MarketScanner
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.composite_scorer import CompositeScorer
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.decision_memory import DecisionMemory
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.use_cases.trade.watch_stocks import WatchStocks


@dataclass(slots=True)
class Pipeline:
    """
    Exposes the stock-trading operations used by CLI, API and schedulers.

    Each public method represents one complete application operation.

    Technical settings are loaded once at the beginning of each workflow.
    The loaded snapshot remains fixed until that workflow completes.
    """

    account_loader: AccountLoader
    account_risk_check: AccountRiskCheck
    market_scanner: MarketScanner
    data_collector: MarketDataCollector
    buzz_scanner: BuzzScanner
    news: NewsFeed
    ai: AiAnalyser
    technical_filter: TechnicalFilter
    composite_scorer: CompositeScorer
    watch_stocks: WatchStocks
    signals: Signals
    decision_memory: DecisionMemory
    order_execution: OrderExecution
    reporting: Reporting
    technical_settings_repository: ITechnicalSettingsRepository
    logger: ILoggingProvider

    async def run_full_cycle(self) -> PipelineStatus:
        """After-market full-universe analysis."""
        settings = await self.technical_settings_repository.load()
        strategy = settings.active_strategy
        status = PipelineStatus()

        self.logger.info(f"Starting full market cycle. Strategy={strategy.strategy_id}.")

        await self.account_loader.execute(status)
        await self.market_scanner.execute(status)
        await self.data_collector.execute(status.universe_stocks, status, strategy.indicators)
        status.survivors = await self.technical_filter.execute(status.universe_stocks, status, strategy)
        await self.news.execute(status.survivors, status)
        await self.ai.execute(status.survivors, status, AiAnalysisFocus.FUNDAMENTAL)
        self.composite_scorer.execute(status.survivors)
        status.watchlist = await self.watch_stocks.execute(status.survivors, WatchlistType.TECHNICAL)
        await self.signals.execute(status.watchlist, status)
        await self.decision_memory.execute(status)
        await self.reporting.execute(status)

        status.stats.finish()

        self.logger.info(
            f"Full market cycle completed. "
            f"Scanned={status.stats.total_scanned}, "
            f"Survivors={len(status.survivors)}, "
            f"Signals={status.stats.signals_generated}."
        )

        # NOTE: Full Cycle currently runs after market close, so it never submits orders.
        return status

    async def run_buzz_scan(self) -> PipelineStatus:
        """Runs short-term social momentum analysis."""
        settings = await self.technical_settings_repository.load()
        strategy = settings.buzz_strategy
        status = PipelineStatus()

        self.logger.info(f"Starting social buzz cycle. Strategy={strategy.strategy_id}, AI focus={AiAnalysisFocus.MOMENTUM.value}.")

        await self.account_loader.execute(status)
        await self.data_collector.refresh_realtime(status.held_stocks, status)
        await self.account_risk_check.execute(status)
        await self.buzz_scanner.execute(status)

        status.stats.total_scanned = len(status.buzz_stocks)

        await self.data_collector.execute(status.buzz_stocks, status, strategy.indicators)
        status.survivors = await self.technical_filter.execute(status.buzz_stocks, status, strategy)
        status.watchlist = await self.watch_stocks.execute(status.survivors, WatchlistType.BUZZ)
        await self.news.execute(status.survivors, status)
        await self.ai.execute(status.survivors, status, AiAnalysisFocus.MOMENTUM)
        self.composite_scorer.execute(status.survivors)
        await self.data_collector.refresh_realtime(status.survivors, status)
        await self.signals.execute(status.watchlist, status)
        await self.decision_memory.execute(status)
        await self.order_execution.execute(status.signals, status)
        await self.reporting.execute(status)

        status.stats.finish()

        self.logger.info(
            f"Social buzz cycle completed. "
            f"Candidates={len(status.buzz_stocks)}, "
            f"Qualified={len(status.survivors)}, "
            f"Orders={status.stats.orders_submitted}."
        )

        return status

    async def run_intraday(self) -> PipelineStatus:
        """Revalidates held and watched stocks before order submission."""
        settings = await self.technical_settings_repository.load()
        strategy = settings.active_strategy
        status = PipelineStatus()

        self.logger.info(f"Starting intraday trading cycle. Strategy={strategy.strategy_id}.")

        await self.account_loader.execute(status)
        candidates = await self.market_scanner.load_intraday_candidates(status)
        await self.data_collector.refresh_realtime(candidates, status)
        await self.account_risk_check.execute(status)

        status.stats.total_scanned = len(candidates)
        blocked_stock_ids = status.risk_blocked_stock_ids | status.stale_stock_ids
        analysis_candidates = [stock for stock in candidates if stock.stock_id not in blocked_stock_ids]

        await self.data_collector.execute(analysis_candidates, status, strategy.indicators)

        technical_candidates = [stock for stock in analysis_candidates if stock.ohlcv]

        status.survivors = await self.technical_filter.execute(technical_candidates, status, strategy)

        held_candidates = [stock for stock in technical_candidates if stock.stock_id in status.positions_by_stock_id]
        decision_candidates = list({stock.stock_id: stock for stock in [*status.survivors, *held_candidates]}.values())

        await self.news.execute(decision_candidates, status)
        await self.ai.execute(decision_candidates, status, AiAnalysisFocus.FUNDAMENTAL)
        self.composite_scorer.execute(decision_candidates)

        await self.data_collector.refresh_realtime(decision_candidates, status)

        await self.signals.execute(StockWatchlist(willing_stocks=decision_candidates), status)
        await self.decision_memory.execute(status)
        await self.order_execution.execute(status.signals, status)
        await self.reporting.execute(status)

        status.stats.finish()
        self.logger.info("Intraday trading cycle completed.")

        return status

    async def analyse_specific_stocks(self, stock_ids: list[str]) -> PipelineStatus:
        """Produces complete reports for explicitly requested stocks."""
        settings = await self.technical_settings_repository.load()
        strategy = settings.active_strategy
        status = PipelineStatus()

        self.logger.info(f"Starting specific-stock analysis: {stock_ids}")

        status.manual_stocks = await self.market_scanner.find_stocks_by_ids(stock_ids, status)

        if not status.manual_stocks:
            status.stats.finish()
            self.logger.info("Specific-stock analysis completed. No requested stocks were loaded.")
            return status

        await self.data_collector.execute(status.manual_stocks, status, strategy.indicators)

        status.survivors = await self.technical_filter.execute(status.manual_stocks, status, strategy)

        # Human override: Technical failure does not stop News, AI, or reporting.
        await self.news.execute(status.manual_stocks, status)
        await self.ai.execute(status.manual_stocks, status, AiAnalysisFocus.FUNDAMENTAL)
        self.composite_scorer.execute(status.manual_stocks)
        await self.reporting.execute(status)

        status.stats.finish()
        self.logger.info("Specific-stock analysis completed.")

        return status
