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
    Writes the stock page's AI brief, one per stock and day in Taipei, which the site pays for once; BriefLookup answers
    what the site holds of it afterwards.

    It first takes today's brief for this request. Another request that is writing or wrote the day's brief keeps it,
    and this one asks no AI. A failed brief, and one a stopped server left being written, is taken over.
    BriefLimitReached when the stock has no brief of the day and stock_page.brief.daily_stocks stocks have one
    already. The request that took the brief writes it: one call of the user's counted AI provider with the prompt
    built from the context's held facts, then only the reply's sentences that hold to the contract (BriefReplyRule).
    A call the user's spent allowance refuses gives the claim back, so it takes none of the day's stocks, and raises
    AiAllowanceSpentError. Any other failed call, a reply that breaks the contract and an empty prompts.stock_brief
    leave the brief failed, which a later request may take over; what the provider answered goes to the log and the
    saved replies alone. `model` is the id of the AI model the user's calls go to.

    `kind` says which of the site's two texts this one writes, and with it the prompt, the reply's part and the limits
    it reads. The daily brief (BriefKind.MOVEMENT) is as above. The company card (BriefKind.COMPANY) is kept under the
    day it was claimed on in a repository of its own, and is the same in every way but when it is written: only while
    prompts.company_card is set, and only when the context's fingerprint differs from that of the company's newest
    written card, so a card is written once and again only when what it rests on changed (BriefKind.daily). The
    companies that may get a card a day are stock_page.card.daily_stocks.

    The world brief (BriefKind.WORLD) is the day's one text about the world, kept under MarketScope.WORLD in place of
    a stock in a repository of its own, from prompts.world_brief and within world.brief's limits. Only the site's own
    writing asks for it, with the context WorldBriefContext gathers when one is due.

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
        self._template, self._sentences, self._daily_stocks, self._reply_rule = config.brief_writing(kind)
        self._claim_limit = None if for_system else self._daily_stocks

    async def execute(self, stock_id: str, context: BriefContext) -> None:
        asked = self._market_clock.now()
        due = self._kind.daily

        if not self._kind.daily and self._template:
            kept = await self._briefs.latest_written(stock_id, asked.date() + timedelta(days=1))
            due = kept is None or kept.fingerprint != context.fingerprint

        if not due:
            return

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
        claimed = await self._briefs.claim(brief, self._claim_limit, asked - self._claim_time)

        if not claimed and await self._briefs.find(brief.stock_id, brief.day) is None:
            raise BriefLimitReached("Today's new AI briefs are spent. They renew at midnight Taiwan time.")

        if not claimed:
            return

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
