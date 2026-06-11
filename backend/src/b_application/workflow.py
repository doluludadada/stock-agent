from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.pipeline_context import PipelineContext
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.collect.market_scanner import MarketScanner
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.order_execution import OrderExecution


class TradingWorkflow:
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
        self._signals = signals
        self._order_execution = order_execution
        self._reporting = reporting
        self._logger = logger

    async def run_full_cycle(self):
        """
        After-market full-universe analysis.
        """
        context = PipelineContext()
        self._logger.info("Starting full market cycle.")

        await self._account_loader.execute(context)
        await self._account_risk_check.execute(context)
        await self._market_scanner.execute(context)
        await self._data_collector.execute(context.universe_stocks, context)
        context.survivors = await self._technical_filter.execute(context.universe_stocks, context)
        await self._news.execute(context.survivors, context)
        await self._ai.execute(context.survivors, context)
        context.watchlist.add_many(context.survivors)

        await self._signals.execute(context.watchlist, context)
        await self._reporting.execute(context)
        context.stats.finish()

        self._logger.info(
            f"Full market cycle completed. "
            f"Scanned={context.stats.total_scanned}, "
            f"Survivors={len(context.survivors)}, "
            f"Signals={context.stats.signals_generated}"
        )
        # NOTE: Might run auto trading.
        # TODO: Create a bool in config if it's true then call order usecase.
        return context

    async def run_buzz_scan(self):
        """
        Finds currently discussed stocks and evaluates them.

        Only technically qualified buzz stocks are persisted to the
        watchlist.

        Orders are passed to OrderExecution, which must enforce:
        - market-open status
        - valid signal quantity
        - account and broker constraints
        """
        pass

    async def run_intraday(self):
        """
        Revalidates held positions and active watchlist candidates
        using current market data before submitting permitted orders.
        """
        pass

    async def analyse_specific_stocks(
        self,
        stock_ids: list[str],
    ):
        """
        Produces complete reports for explicitly requested stocks.

        Passing stocks are returned as MANUAL watchlist candidates.
        Persisting them remains an explicit user action.
        """
        self._logger.info(f"Starting specific-stock analysis: {stock_ids}")

        pass
