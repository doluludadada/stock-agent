"""
Use Case: Analyze sentiment using AI.

Orchestrates: Domain(PromptBuilder) -> Infra(AiPort) -> Domain(Parser)
"""
from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.model.chat.message import Message, MessageRole
from src.a_domain.ports.system.ai_provider import IAiProvider
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.a_domain.rules.process.ai.parser import SentimentResponseParser
from src.a_domain.rules.process.ai.prompt import SentimentPromptBuilder


class AnalyzeSentiment:
    """
    Orchestrates AI sentiment analysis.
    
    Flow:
    1. Build prompt using domain rule (PromptBuilder)
    2. Call AI via infrastructure port
    3. Parse response using domain rule (Parser)
    """

    def __init__(
        self,
        ai_provider: IAiProvider,
        prompt_builder: SentimentPromptBuilder,
        response_parser: SentimentResponseParser,
        logger: ILoggingProvider,
    ):
        self._ai = ai_provider
        self._prompt_builder = prompt_builder
        self._response_parser = response_parser
        self._logger = logger

    async def execute(self, contexts: list[AnalysisContext]) -> list[AnalysisContext]:
        self._logger.info(f"Analyzing sentiment for {len(contexts)} stocks...")
        analyzed_count = 0

        for ctx in contexts:
            if not ctx.articles:
                self._logger.debug(f"No articles for {ctx.stock.stock_id}, using neutral score")
                ctx.sentiment_score = 50
                continue

            try:
                # 1. Build prompt (domain rule)
                prompt = self._prompt_builder.build(
                    ctx.stock.stock_id,
                    ctx.source,
                    ctx.articles,
                )

                # 2. Call AI (infrastructure)
                messages = (Message(role=MessageRole.USER, content=prompt),)
                response = await self._ai.generate_reply(messages)

                # 3. Parse response (domain rule)
                report = self._response_parser.parse(ctx.stock.stock_id, response.content)

                # 4. Update context
                ctx.sentiment_report = report
                ctx.sentiment_score = report.score
                analyzed_count += 1

            except Exception as e:
                self._logger.error(f"Sentiment analysis failed for {ctx.stock.stock_id}: {e}")
                ctx.sentiment_score = 50

        self._logger.success(f"Sentiment analysis complete: {analyzed_count} stocks analyzed")
        return contexts
