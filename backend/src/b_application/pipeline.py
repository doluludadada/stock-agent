from warnings import deprecated

from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.pipeline_context import PipelineContext
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.process.ai_analyser import AiAnalyser


@deprecated("Might delete")
class AnalysisPipeline:
    """
    Runs the common news and AI analysis sequence.

    Candidate loading, market-data collection, technical filtering,
    signal generation, watchlist persistence, order execution and reporting belong to
    the surrounding TradingWorkflow.
    """

    def __init__(
        self,
        news_feed: NewsFeed,
        ai_analyser: AiAnalyser,
        logger: ILoggingProvider,
    ) -> None:
        self._news_feed = news_feed
        self._ai_analyser = ai_analyser
        self._logger = logger

    async def execute(
        self,
        context: PipelineContext,
    ) -> None:
        if context.survivors:
            return

        self._logger.info("Analysis pipeline skipped. No technical survivors.")
