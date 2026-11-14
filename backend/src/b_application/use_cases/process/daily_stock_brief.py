from datetime import timedelta

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.model.chat.message import Message
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.stock_brief_repository import IStockBriefRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.ai.stock_brief import BriefContext, BriefPromptBuilder
from a_domain.types.enums import BriefKind, BriefStatus, MessageRole
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

    `kind` says which of the site's two texts this one writes, and with it the prompt, the reply's part and the limits
    it reads. The daily brief (BriefKind.MOVEMENT) is as above. The company card (BriefKind.COMPANY) is kept under the
    day it was claimed on in a repository of its own, and is the same in every way but when it is written: only while
    prompts.company_card is set, and only when the context's fingerprint differs from that of the company's newest
    written card, so a card is written once and again only when what it rests on changed (BriefKind.daily). Its answer
    is today's card if one was claimed today, the newest written card of an earlier day, and how many more companies
    may get a card today (stock_page.card.daily_stocks).

    `for_system` says the site writes by itself, on the provider that counts the system's own calls: no limit of
    stocks holds its claim, and its text takes none of the day's stocks, which are the viewers'.
    """

    def __init__(
        self,
        briefs: IStockBriefRepository,
        ai_provider: IAiProvider,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
        model: str,
        kind: BriefKind = BriefKind.MOVEMENT,
        for_system: bool = False,
    ) -> None:
        self._briefs = briefs
        self._ai_provider = ai_provider
        self._market_clock = market_clock
        self._logger = logger
        self._model = model
        self._kind = kind
        self._language = config.stock_page.brief.language
        self._claim_time = timedelta(minutes=config.stock_page.brief.claim_minutes)
        brief, card, advice = config.stock_page.brief, config.stock_page.card, config.prompts.advice_phrases()

        match kind:
            case BriefKind.MOVEMENT:
                self._template, self._sentences, self._daily_stocks = config.prompts.stock_brief, brief.sentences, brief.daily_stocks
                self._reply_rule = brief.reply_rule(advice)
            case BriefKind.COMPANY:
                self._template, self._sentences, self._daily_stocks = config.prompts.company_card, card.sentences, card.daily_stocks
                self._reply_rule = card.reply_rule(advice, brief.link_pattern)

        self._claim_limit = None if for_system else self._daily_stocks

    async def execute(self, stock_id: str, context: BriefContext | None = None) -> tuple[StockBrief | None, StockBrief | None, int]:
        asked = self._market_clock.now()
        brief = None
        due = context is not None and self._kind.daily

        if context is not None and not self._kind.daily and self._template:
            kept = await self._briefs.latest_written(stock_id, asked.date() + timedelta(days=1))
            due = kept is None or kept.fingerprint != context.fingerprint

        if context is not None and due:
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
                fingerprint=context.fingerprint,
            )

        claimed = brief is not None and await self._briefs.claim(brief, self._claim_limit, asked - self._claim_time)

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
