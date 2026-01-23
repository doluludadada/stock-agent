from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.model.chat.message import Message, MessageRole
from src.a_domain.ports.system.ai_port import IAiPort
from src.a_domain.ports.system.logging_port import ILoggingPort
from src.a_domain.rules.process.sentiment_parser import SentimentResponseParser
from src.a_domain.rules.process.sentiment_prompt import SentimentPromptBuilder


class SentimentAnalyser:
    """
    Use Case: Orchestrate the AI Sentiment Analysis process.
    Flow: Domain(Builder) -> Infra(AiPort) -> Domain(Parser)
    """

    def __init__(
        self,
        ai_port: IAiPort,
        prompt_builder: SentimentPromptBuilder,
        response_parser: SentimentResponseParser,
        logger: ILoggingPort,
    ):
        self._ai_port = ai_port
        self._prompt_builder = prompt_builder
        self._response_parser = response_parser
        self._logger = logger

    async def execute(self, contexts: list[AnalysisContext]) -> list[AnalysisContext]:
        self._logger.info(f"Running sentiment analysis on {len(contexts)} stocks")
        analyzed_count = 0

        for ctx in contexts:
            if not ctx.articles:
                self._logger.debug(
                    f"No articles for {ctx.stock.stock_id}, skipping sentiment"
                )
                ctx.sentiment_score = 50
                continue

            try:
                # 1. Build Prompt (Domain Rule)
                prompt_content = self._prompt_builder.build(
                    ctx.stock.stock_id, ctx.articles
                )
                messages = (Message(role=MessageRole.USER, content=prompt_content),)

                # 2. Call AI (Infrastructure Port)
                response_msg = await self._ai_port.generate_reply(messages)

                # 3. Parse Response (Domain Rule)
                report = self._response_parser.parse(
                    ctx.stock.stock_id, response_msg.content
                )

                # 4. Update Context
                ctx.sentiment_report = report
                ctx.sentiment_score = report.confidence_score
                analyzed_count += 1

            except Exception as e:
                self._logger.error(
                    f"Sentiment analysis failed for {ctx.stock.stock_id}: {e}"
                )
                ctx.sentiment_score = 50

        self._logger.success(f"Sentiment analysis complete for {analyzed_count} stocks")
        return contexts
