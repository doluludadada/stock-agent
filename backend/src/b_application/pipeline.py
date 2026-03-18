from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.pipeline_context import PipelineContext
from b_application.use_cases.collect.market_data import MarketData
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.collect.stock_selector import StockSelector
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.monitoring import Monitoring
from b_application.use_cases.trade.order_execution import OrderExecution


class Pipeline:
    def __init__(
        self,
        stock_selector: StockSelector,
        market_data: MarketData,
        technical_filter: TechnicalFilter,
        news_feed: NewsFeed,
        ai_analyser: AiAnalyser,
        signals: Signals,
        order_execution: OrderExecution,
        reporting: Reporting,
        monitoring: Monitoring,
        logger: ILoggingProvider,
    ):
        self._stock_selector = stock_selector
        self._market_data = market_data
        self._technical_filter = technical_filter
        self._news_feed = news_feed
        self._ai_analyser = ai_analyser
        self._signals = signals
        self._order_execution = order_execution
        self._reporting = reporting
        self._monitoring = monitoring
        self._logger = logger

    async def execute(self, workflow_state: PipelineContext):
        self._logger.info(">>> Intraday Pipeline Started")

        try:
            # ---------------------------------------------------------------------------- #
            #                Flow A: Sell Flow (Monitor Existing Positions)                #
            # ---------------------------------------------------------------------------- #
            await self._monitoring.execute(workflow_state)
            if workflow_state.exit_signals:
                workflow_state.orders_submitted += await self._order_execution.execute(workflow_state.exit_signals)
                await self._reporting.execute(workflow_state.exit_signals)

            # ---------------------------------------------------------------------------- #
            #                    Flow B: Buy Flow (New Candidate Funnel)                   #
            # ---------------------------------------------------------------------------- #
            # 1. Select stocks from watchlists
            await self._stock_selector.execute(workflow_state)
            if not workflow_state.candidates:
                self._logger.info("No stocks selected. Terminating Buy Flow.")
                return

            # 2. Collect market prices
            await self._market_data.execute(workflow_state)
            if not workflow_state.priced:
                self._logger.info("No price data available. Terminating Buy Flow.")
                return

            # 3. Technical filter (Quantitative)
            self._technical_filter.execute(workflow_state)
            if not workflow_state.survivors:
                self._logger.info("No stocks survived the technical filter. Terminating Buy Flow.")
                return

            # 4. Collect articles and run AI Analysis (Qualitative Right Brain)
            await self._news_feed.execute(workflow_state)
            await self._ai_analyser.execute(workflow_state)

            # 5. Generate signals and execute
            await self._signals.execute(workflow_state)
            if workflow_state.buy_signals:
                workflow_state.orders_submitted += await self._order_execution.execute(workflow_state.buy_signals)
                await self._reporting.execute(workflow_state.buy_signals)

        except Exception as e:
            self._logger.exception(f"Pipeline crashed: {e}")
            workflow_state.stats.add_error(str(e))

        finally:
            self._logger.info(f"<<< Pipeline Finished. Total Orders Submitted: {workflow_state.orders_submitted}")
