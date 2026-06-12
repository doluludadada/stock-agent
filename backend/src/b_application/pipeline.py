from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.pipeline_status import PipelineStatus
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
        status = PipelineStatus()
        self._logger.info("Starting full market cycle.")

        await self._account_loader.execute(status)
        await self._account_risk_check.execute(status)
        await self._market_scanner.execute(status)
        await self._data_collector.execute(status.universe_stocks, status)
        status.survivors = await self._technical_filter.execute(status.universe_stocks, status)
        await self._news.execute(status.survivors, status)
        await self._ai.execute(status.survivors, status)
        status.watchlist.add_many(status.survivors)

        await self._signals.execute(status.watchlist, status)
        await self._reporting.execute(status)
        status.stats.finish()

        self._logger.info(
            f"Full market cycle completed. "
            f"Scanned={status.stats.total_scanned}, "
            f"Survivors={len(status.survivors)}, "
            f"Signals={status.stats.signals_generated}"
        )
        # NOTE: Might run auto trading.
        # TODO: Create a bool in config if it's true then call order usecase.
        # But it always run after market
        return status

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

    async def run_intraday(self, status: PipelineStatus):
        """
        Revalidates held positions and active watchlist candidates
        using current market data before submitting permitted orders.
        """
        # TODO: If status is none. Run a full cycle? hmmm? Or this function shouldnt run independly?
        pass

    async def analyse_specific_stocks(self, stock_ids: list[str]):
        """
        Produces complete reports for explicitly requested stocks.

        Passing stocks are returned as MANUAL watchlist candidates.
        Persisting them remains an explicit user action.
        """
        self._logger.info(f"Starting specific-stock analysis: {stock_ids}")
        status = PipelineStatus()  # ? create a new status?
        status.manual_stocks = await self._market_scanner.find_stocks_by_ids(stock_ids, status)

        if not status.manual_stocks:
            status.stats.finish()
            return status

        await self._data_collector.execute(status.manual_stocks, status)

        status.survivors = await self._technical_filter.execute(status.manual_stocks, status)

        await self._news.execute(status.manual_stocks, status)

        await self._ai.execute(status.manual_stocks, status)

        await self._reporting.execute(status)

        status.stats.finish()
        return status

        # TODO: Needa find somewhere to change stock.candidate_source = WatchlistType.MANUAL

        """
        # TODO:
        Manual watchlist add belongs after user confirmation
        if context.survivors and Confirm.ask("Add passing stocks to manual watchlist?", default=False):
        context.watchlist.add_many(context.survivors)
        await workflow.add_manual_watchlist(context.watchlist)
        """
