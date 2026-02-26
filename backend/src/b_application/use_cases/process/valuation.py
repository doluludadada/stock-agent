from backend.src.a_domain.model.chat.message import Message, MessageRole
from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.ports.chat.knowledge_repository import IKnowledgeRepository
from backend.src.a_domain.ports.system.ai_provider import IAiProvider
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.rules.process.ai.parser import SentimentParser
from backend.src.a_domain.rules.process.ai.prompt import SentimentPromptBuilder


class Valuation:
    def __init__(
        self,
        ai_provider: IAiProvider,
        prompt_builder: SentimentPromptBuilder,
        response_parser: SentimentParser,
        knowledge_repo: IKnowledgeRepository,
        logger: ILoggingProvider,
        neutral_score: int = 50,
    ):
        self._ai = ai_provider
        self._prompt_builder = prompt_builder
        self._response_parser = response_parser
        self._knowledge = knowledge_repo
        self._logger = logger
        self._neutral_score = neutral_score

    async def execute(self, candidates: list[Stock]) -> list[Stock]:
        self._logger.info(f"Analyzing sentiment for {len(candidates)} stocks...")
        analyzed_count = 0

        for candidate in candidates:
            if not candidate.articles:
                self._logger.debug(f"No articles for {candidate.stock_id}, using neutral score")
                candidate.sentiment_score = self._neutral_score
                continue

            try:
                # 1. Enrich with RAG context
                try:
                    candidate.historical_context = await self._knowledge.search(candidate.stock_id)
                except Exception as e:
                    self._logger.error(f"RAG read failed for {candidate.stock_id}: {e}")

                # 2. Build prompt
                prompt = self._prompt_builder.build(candidate)

                # 3. Call AI
                messages = (Message(role=MessageRole.USER, content=prompt),)
                response = await self._ai.generate_reply(messages)

                # 4. Parse response
                report = self._response_parser.parse(candidate.stock_id, response.content)

                # 5. Update candidate
                candidate.sentiment_report = report
                candidate.sentiment_score = report.score
                analyzed_count += 1

            except Exception as e:
                self._logger.error(f"Sentiment analysis failed for {candidate.stock_id}: {e}")
                candidate.sentiment_score = self._neutral_score

        self._logger.info(f"Sentiment analysis complete: {analyzed_count} stocks analyzed")
        return candidates
