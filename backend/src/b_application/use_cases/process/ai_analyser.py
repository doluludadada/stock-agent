from icontract import require

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.ai.parser import AiReportParser
from a_domain.rules.ai.prompt import AiReportPromptBuilder
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class AiAnalyser:
    """
    Analyses technically valid candidate stocks with the configured AI provider.

    Responsibilities:
    - load previous decision context from the knowledge repository
    - build the AI analysis prompt
    - request an AI response
    - parse the response into an AiAnalysisReport
    - attach the report and score to the runtime Stock
    - record analysis failures
    """

    def __init__(
        self,
        ai_provider: IAiProvider,
        knowledge_repository: IKnowledgeRepository,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._ai_provider = ai_provider
        self._knowledge_repository = knowledge_repository
        self._logger = logger

        self._prompt_builder = AiReportPromptBuilder(
            fundamental_template=config.prompts.analysis_report_fundamental,
            momentum_template=config.prompts.analysis_report_momentum,
            max_articles=config.analysis.article_fetch_limit,
            max_content_length=config.ai.article_content_length,
        )
        self._report_parser = AiReportParser()

    @require(
        lambda context: len(context.survivors) > 0,
        "AI analysis requires at least one surviving stock",
    )
    async def execute(self, context: PipelineContext) -> None:
        analysed_count = 0
        stocks = context.survivors
        self._logger.info(f"Analysing {len(stocks)} surviving stocks.")
        for stock in stocks:
            # Clean first
            stock.analysis_report = None
            stock.ai_score = None
            stock.historical_context = ""

            # Search pervious history
            try:
                stock.historical_context = await self._knowledge_repository.search(
                    query=stock.stock_id,
                )
            except Exception as error:
                self._logger.warning(f"Previous decision context unavailable for {stock.stock_id}: {error}")

            try:
                prompt = self._prompt_builder.build(stock)

                response = await self._ai_provider.generate_reply(
                    messages=(
                        Message(
                            role=MessageRole.USER,
                            content=prompt,
                        ),
                    ),
                )

                # TODO: Too many try here
                try:
                    self._ai_provider.save_response(
                        stock_id=stock.stock_id,
                        content=response.content,
                    )
                except Exception as error:
                    self._logger.warning(f"Failed to archive AI response for {stock.stock_id}: {error}")

                report = self._report_parser.parse(
                    stock_id=stock.stock_id,
                    raw_response=response.content,
                )

                stock.analysis_report = report
                stock.ai_score = report.score
                analysed_count += 1

            except Exception as error:
                error_message = f"AI analysis failed for {stock.stock_id}: {error}"

                self._logger.error(error_message)
                context.stats.add_error(error_message)
                stock.analysis_report = None
                stock.ai_score = None

        context.stats.ai_analysed += analysed_count

        self._logger.info(f"AI analysis completed: {analysed_count}/{len(stocks)} stocks analysed.")
