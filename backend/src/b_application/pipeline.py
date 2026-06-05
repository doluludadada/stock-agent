# backend/src/b_application/pipeline.py

from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.pipeline_context import PipelineContext
from b_application.use_cases.collect.market_data import MarketData
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.collect.stock_selector import StockSelector
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.order_execution import OrderExecution


class Pipeline:
    """
    Intraday full-funnel pipeline.

    This pipeline must produce one final decision per analysed stock:
    BUY, SELL, or HOLD.

    Important:
    Monitoring is intentionally not executed here.
    Score-based exit must run through the same full funnel as entry:
    AccountLoader -> StockSelector -> MarketData -> TechnicalFilter -> NewsFeed -> AiAnalyser -> Signals.
    """

    def __init__(
        self,
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
        logger: ILoggingProvider,
    ):
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
        self._logger = logger

    async def execute(self, context: PipelineContext) -> None:
        """
        Executes one complete intraday decision cycle.

        OrderExecution and Reporting must run once at the end.
        Running them before Signals creates duplicate side effects.
        """
        self._logger.info(">>> Intraday Pipeline Started")

        try:
            await self._account_loader.execute(context)
            await self._account_risk_check.execute(context)
            await self._stock_selector.execute(context)

            # Flat sequence: Only run the next step if the previous step produced results
            if context.candidates:
                await self._market_data.execute(context)
            if context.priced:
                await self._technical_filter.execute(context)
            if context.survivors:
                await self._news_feed.execute(context)
                await self._ai_analyser.execute(context)

            # Execute final decisions if we have either new candidates OR emergency stops
            if context.survivors or context.emergency_exit_signals:
                await self._signals.execute(context)
                await self._order_execution.execute(context)
                await self._reporting.execute(context)
            else:
                self._logger.info("No actionable candidates or emergency exits. Pipeline resting.")

            context.stats.finish()

        except Exception as e:
            self._logger.exception(f"Pipeline crashed: {e}")
            context.stats.add_error(str(e))

        finally:
            self._logger.info(f"<<< Pipeline Finished. Total Orders Submitted: {context.stats.orders_submitted}")
