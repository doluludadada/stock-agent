from a_domain.model.chat.message import Message
from a_domain.model.market.stock import Stock
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.ai.parser import AiReportParser
from a_domain.rules.ai.prompt import AiReportPromptBuilder
from a_domain.types.enums import MessageRole
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


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

    async def execute(
        self,
        stocks: list[Stock],
        status: PipelineStatus,
    ) -> None:
        self._logger.info(f"Analysing {len(stocks)} stocks.")

        analysed_count = 0

        for stock in stocks:
            try:
                stock.analysis_report = None
                stock.ai_score = None
                stock.historical_context = await self._knowledge_repository.search(stock.stock_id)

                prompt = self._prompt_builder.build(stock)

                response = await self._ai_provider.generate_reply(
                    messages=(
                        Message(
                            role=MessageRole.USER,
                            content=prompt,
                        ),
                    ),
                )

                self._ai_provider.save_response(stock_id=stock.stock_id, content=response.content)
                report = self._report_parser.parse(stock_id=stock.stock_id, raw_response=response.content)

                stock.analysis_report = report
                stock.ai_score = report.score
                analysed_count += 1

            except Exception as error:
                message = f"AI analysis failed for {stock.stock_id}: {error}"
                self._logger.error(message)
                status.stats.add_error(message)

        status.stats.ai_analysed += analysed_count
        self._logger.info(f"AI analysis completed: {analysed_count}/{len(stocks)} stocks analysed.")
