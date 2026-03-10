from a_domain.model.chat.message import Message, MessageRole
from a_domain.model.market.stock import Stock
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.process.ai.parser import AiReportParser
from a_domain.rules.process.ai.prompt import AiReportPromptBuilder
from b_application.schemas.config import AppConfig


class AiAnalyser:
    def __init__(
        self,
        ai_provider: IAiProvider,
        prompt_builder: AiReportPromptBuilder,
        response_parser: AiReportParser,
        knowledge_repo: IKnowledgeRepository,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._ai = ai_provider
        self._prompt_builder = prompt_builder
        self._response_parser = response_parser
        self._knowledge = knowledge_repo
        self._config = config
        self._logger = logger

    async def execute(self, stocks: list[Stock]) -> list[Stock]:
        self._logger.info(f"Analyzing AI context for {len(stocks)} stocks...")
        analyzed_count = 0

        for stock in stocks:
            if not stock.articles:
                stock.ai_score = self._config.ai_neutral_score
                continue

            try:
                try:
                    stock.historical_context = await self._knowledge.search(stock.stock_id)
                except Exception as e:
                    self._logger.error(f"RAG read failed for {stock.stock_id}: {e}")

                prompt = self._prompt_builder.build(stock)
                messages = (Message(role=MessageRole.USER, content=prompt),)
                response = await self._ai.generate_reply(messages)

                report = self._response_parser.parse(stock.stock_id, response.content)
                stock.analysis_report = report
                stock.ai_score = report.score
                analyzed_count += 1
            except Exception as e:
                self._logger.error(f"AI analysis failed for {stock.stock_id}: {e}")
                stock.ai_score = self._config.ai_neutral_score

        self._logger.info(f"AI analysis complete: {analyzed_count} stocks analyzed")
        return stocks
