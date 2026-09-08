# backend/src/b_application/use_cases/process/ai_analyser.py

from a_domain.model.chat.message import Message
from a_domain.model.market.stock import Stock
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.ai.parser import AiReportParser
from a_domain.rules.ai.prompt import AiReportPromptBuilder
from a_domain.types.enums import AiAnalysisFocus, MessageRole
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class AiAnalyser:
    """
    Analyses workflow-selected candidate stocks with the configured AI provider.

    Automatic workflows normally pass technically valid survivors.
    Manual specific-stock analysis may intentionally pass technical failures
    so a human can review a complete report before overriding the system.
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
        focus: AiAnalysisFocus,
    ) -> None:
        self._logger.info(f"Analysing {len(stocks)} stocks. Focus={focus.value}.")
        analysed_count = 0

        for stock in stocks:
            try:
                stock.ai_report = None
                historical_context = await self._knowledge_repository.search(stock.stock_id)
                prompt = self._prompt_builder.build(stock=stock, historical_context=historical_context, focus=focus)
                response = await self._ai_provider.generate_reply(messages=(Message(role=MessageRole.USER, content=prompt),))
                self._ai_provider.save_response(stock.stock_id, response.content)
                stock.ai_report = self._report_parser.parse(stock.stock_id, response.content)
                analysed_count += 1
            except Exception as error:
                message = f"AI analysis failed for {stock.stock_id}: {error}"
                self._logger.error(message)
                status.stats.add_error(message)

        status.stats.ai_analysed += analysed_count
        self._logger.info(f"AI analysis completed: {analysed_count}/{len(stocks)} stocks analysed.")
