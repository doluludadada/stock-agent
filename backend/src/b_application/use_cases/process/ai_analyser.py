from icontract import require

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.ai.parser import AiReportParser
from a_domain.rules.ai.prompt import AiReportPromptBuilder
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


# TODO: check the survivors and add to watchlist.
class AiAnalyser:
    def __init__(
        self,
        ai_provider: IAiProvider,
        knowledge_repo: IKnowledgeRepository,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._ai = ai_provider
        self._knowledge = knowledge_repo
        self._config = config
        self._prompt_builder = AiReportPromptBuilder(
            fundamental_template=config.prompts.analysis_report_fundamental,
            momentum_template=config.prompts.analysis_report_momentum,
            max_articles=config.analysis.article_fetch_limit,
            max_content_length=config.ai.article_content_length,
        )
        self._response_parser = AiReportParser()
        self._logger = logger

    @require(lambda context: len(context.survivors) > 0, "Pipeline guarantees survivors exist")
    async def execute(self, context: PipelineContext) -> None:
        stocks = context.survivors
        self._logger.info(f"Analysing AI context for {len(stocks)} stocks...")
        analysed_count = 0

        for stock in stocks:
            if not stock.articles:
                stock.analysis_report = self._response_parser.parse(stock.stock_id, "")
                stock.ai_score = stock.analysis_report.score
                continue

            try:
                try:
                    stock.historical_context = await self._knowledge.search(stock.stock_id)
                except Exception as e:
                    self._logger.error(f"RAG read failed for {stock.stock_id}: {e}")

                prompt = self._prompt_builder.build(stock)
                messages = (Message(role=MessageRole.USER, content=prompt),)
                response = await self._ai.generate_reply(messages)

                # Persist raw AI response via provider method
                self._ai.save_response(stock.stock_id, response.content)

                report = self._response_parser.parse(stock.stock_id, response.content)
                stock.analysis_report = report
                stock.ai_score = report.score
                analysed_count += 1

            except Exception as e:
                error_message = f"AI analysis failed for {stock.stock_id}: {e}"
                self._logger.error(error_message)
                context.stats.add_error(error_message)
                stock.analysis_report = self._response_parser.parse(stock.stock_id, "")
                stock.ai_score = stock.analysis_report.score

        context.stats.ai_analysed += analysed_count
        self._logger.info(f"AI analysis complete: {analysed_count} stocks analysed")
