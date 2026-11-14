from datetime import timedelta

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.model.chat.message import Message
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.stock_brief_repository import IStockBriefRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.ai.stock_brief import BriefContext, BriefPromptBuilder
from a_domain.types.enums import BriefStatus, MessageRole
from a_domain.types.errors import AiAllowanceSpentError, BriefLimitReached
from b_application.config.app_config import AppConfig


class DailyStockBrief:
    """
    The stock page's AI brief, one per stock and day in Taipei, which the site pays for once.

    Without a context it asks no AI and answers what the site holds: the stock's brief of today if a viewer asked for
    one, its newest written brief of an earlier day, which the page shows while today's is being written or after it
    failed, and how many more stocks may get a new brief today (stock_page.brief.daily_stocks). A brief still being
    written stock_page.brief.claim_minutes after its claim was left behind by a stopped server: it is answered as
    failed, so the page offers to ask again, and the next request takes it over.

    With a context it first takes today's brief for this request, and answers the same. Another request that is
    writing or wrote the day's brief keeps it, and this one asks no AI. A failed brief, and one a stopped server left
    being written, is taken over. BriefLimitReached when the stock has no brief of the day and daily_stocks stocks
    have one already. The request that took the brief writes it: one call of the user's counted AI provider with the
    prompt built from the context's held facts, then only the reply's sentences that hold to the contract
    (BriefReplyRule). A call the user's spent allowance refuses gives the claim back, so it takes none of the day's
    stocks, and raises AiAllowanceSpentError. Any other failed call, a reply that breaks the contract and an empty
    prompts.stock_brief leave the brief failed, which a later request may take over; what the provider answered goes
    to the log and the saved replies alone. `model` is the id of the AI model the user's calls go to.
    """

    def __init__(
        self,
        briefs: IStockBriefRepository,
        ai_provider: IAiProvider,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
        model: str,
    ) -> None:
        self._briefs = briefs
        self._ai_provider = ai_provider
        self._market_clock = market_clock
        self._logger = logger
        self._model = model
        self._template = config.prompts.stock_brief
        self._language = config.stock_page.brief.language
        self._sentences = config.stock_page.brief.sentences
        self._reply_rule = config.stock_page.brief.reply_rule(config.prompts.advice_phrases())
        self._daily_stocks = config.stock_page.brief.daily_stocks
        self._claim_time = timedelta(minutes=config.stock_page.brief.claim_minutes)

    async def execute(self, stock_id: str, context: BriefContext | None = None) -> tuple[StockBrief | None, StockBrief | None, int]:
        asked = self._market_clock.now()
        brief = None

        if context is not None:
            brief = StockBrief(
                stock_id=context.stock_id,
                day=asked.date(),
                status=BriefStatus.WRITING,
                language=self._language,
                model=self._model,
                claimed_at=asked,
                window_first=context.window_first,
                window_last=context.window_last,
                price_change=context.price_change,
            )

        claimed = brief is not None and await self._briefs.claim(brief, self._daily_stocks, asked - self._claim_time)

        if brief is not None and not claimed and await self._briefs.find(brief.stock_id, brief.day) is None:
            raise BriefLimitReached("Today's new AI briefs are spent. They renew at midnight Taiwan time.")

        if brief is not None and context is not None and claimed:
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

        now = self._market_clock.now()
        today = await self._briefs.find(stock_id, now.date())
        previous = await self._briefs.latest_written(stock_id, now.date())
        left = max(0, self._daily_stocks - await self._briefs.claimed_stocks(now.date()))

        if today is not None and today.status == BriefStatus.WRITING and today.claimed_at < now - self._claim_time:
            today.fail()

        return today, previous, left
