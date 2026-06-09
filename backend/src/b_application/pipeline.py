from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.pipeline_context import PipelineContext
from b_application.use_cases.collect.intraday_candidates import (
    IntradayCandidates,
)
from b_application.use_cases.collect.market_data import MarketData
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.order_execution import OrderExecution


class Pipeline:
    def __init__(
        self,
        account_loader: AccountLoader,
        account_risk_check: AccountRiskCheck,
        intraday_candidates: IntradayCandidates,
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
        self._intraday_candidates = intraday_candidates
        self._market_data = market_data
        self._technical_filter = technical_filter
        self._news_feed = news_feed
        self._ai_analyser = ai_analyser
        self._signals = signals
        self._order_execution = order_execution
        self._reporting = reporting
        self._logger = logger

    async def execute(
        self,
        context: PipelineContext,
    ) -> None:
        self._logger.info(">>> Intraday Pipeline Started")

        try:
            await self._account_loader.execute(context)
            await self._account_risk_check.execute(context)
            await self._intraday_candidates.execute(context)

            if context.candidates:
                await self._market_data.execute(context)

            if context.priced:
                await self._technical_filter.execute(context)

            if context.survivors:
                await self._news_feed.execute(context)
                await self._ai_analyser.execute(context)

            if context.survivors or context.emergency_exit_signals:
                await self._signals.execute(context)
                await self._order_execution.execute(context)
                await self._reporting.execute(context)
            else:
                self._logger.info("No actionable candidates or emergency exits.")

            context.stats.finish()

        except Exception as error:
            self._logger.exception(f"Pipeline crashed: {error}")
            context.stats.add_error(str(error))

        finally:
            self._logger.info(f"<<< Pipeline Finished. Total Orders Submitted: {context.stats.orders_submitted}")
