from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.model.chat.message import Message
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.stock_brief_repository import IStockBriefRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.ai.stock_brief import BriefContext, BriefPromptBuilder
from a_domain.types.enums import MessageRole
from a_domain.types.errors import AiAllowanceSpentError
from b_application.config.app_config import AppConfig


class StockBriefWriter:
    """
    Writes the brief a request claimed (StockBriefClaim): one call of the user's counted AI provider with the prompt
    built from the held facts, then only the reply's sentences that hold to the contract (BriefReplyRule). A call the
    user's spent allowance refuses gives the claim back, so it takes none of the day's stocks, and raises
    AiAllowanceSpentError. Any other failed call, a reply that breaks the contract and an empty prompts.stock_brief
    leave the brief failed, which a later request may take over; what the provider answered goes to the log and the
    saved replies alone.
    """

    def __init__(
        self,
        briefs: IStockBriefRepository,
        ai_provider: IAiProvider,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._briefs = briefs
        self._ai_provider = ai_provider
        self._market_clock = market_clock
        self._logger = logger
        self._template = config.prompts.stock_brief
        self._language = config.stock_page.brief.language
        self._sentences = config.stock_page.brief.sentences
        self._reply_rule = config.stock_page.brief.reply_rule(config.prompts.advice_phrases())

    async def execute(self, brief: StockBrief, context: BriefContext) -> None:
        reply = None

        try:
            builder = BriefPromptBuilder(template=self._template, language=self._language, sentences=self._sentences)
            question = Message(role=MessageRole.USER, content=builder.apply(context), timestamp=self._market_clock.now())
            answer = await self._ai_provider.generate_reply((question,))
            self._ai_provider.save_response(brief.stock_id, answer.content)
            reply = self._reply_rule.apply(answer.content, context)
        except AiAllowanceSpentError:
            await self._briefs.release(brief.stock_id, brief.day)
            raise
        except Exception as error:
            self._logger.error(f"Stock brief failed for {brief.stock_id}: {type(error).__name__}: {error}")

        if reply is None:
            brief.fail()
        else:
            brief.write(reply.company, reply.movement, reply.sources, self._market_clock.now())

        await self._briefs.save(brief)
