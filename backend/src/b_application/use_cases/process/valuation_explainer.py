from a_domain.model.chat.message import Message
from a_domain.model.valuation.valuation_explanation import ValuationExplanation
from a_domain.model.valuation.valuation_report import ValuationReport
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.ai.parser import parse_valuation_explanation
from a_domain.rules.ai.prompt import ValuationPromptBuilder
from a_domain.types.enums import MessageRole
from b_application.config.app_config import AppConfig


class ValuationExplainer:
    """Use Case: asks the AI to explain a valuation the domain already computed. A failed call keeps the numbers and says why."""

    def __init__(self, ai_provider: IAiProvider, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._ai_provider = ai_provider
        self._market_clock = market_clock
        self._prompt_builder = ValuationPromptBuilder(
            template=config.prompts.valuation_explanation,
            max_articles=config.analysis.article_fetch_limit,
            max_content_length=config.ai.article_content_length,
        )
        self._logger = logger

    async def execute(self, report: ValuationReport) -> ValuationExplanation:
        stock_id = report.stock.stock_id
        prompt = self._prompt_builder.apply(report)

        try:
            message = Message(role=MessageRole.USER, content=prompt, timestamp=self._market_clock.now())
            response = await self._ai_provider.generate_reply((message,))
        except Exception as error:
            self._logger.error(f"Valuation explanation failed for {stock_id}: {error}")
            return ValuationExplanation.without_ai(report, f"AI explanation unavailable: {error}")

        self._ai_provider.save_response(stock_id, response.content)

        return parse_valuation_explanation(report, response.content)
