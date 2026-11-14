from datetime import timedelta

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.ports.ai.stock_brief_repository import IStockBriefRepository
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.ai.stock_brief import BriefContext
from a_domain.types.enums import BriefStatus
from a_domain.types.errors import BriefLimitReached
from b_application.config.app_config import AppConfig


class StockBriefClaim:
    """
    Takes a stock's AI brief of today in Taipei for one writer, so the site pays for it once: the brief as it stands
    while the AI is asked, or None when this request does not get it because another request is writing or wrote the
    day's brief. A failed brief, and one a stopped server left being written for stock_page.brief.claim_minutes, is
    taken over. BriefLimitReached when the stock has no brief of the day and stock_page.brief.daily_stocks stocks have
    one already. `model` is the id of the AI model the user's calls go to.
    """

    def __init__(self, briefs: IStockBriefRepository, market_clock: IMarketClock, config: AppConfig, model: str) -> None:
        self._briefs = briefs
        self._market_clock = market_clock
        self._model = model
        self._language = config.stock_page.brief.language
        self._daily_stocks = config.stock_page.brief.daily_stocks
        self._claim_time = timedelta(minutes=config.stock_page.brief.claim_minutes)

    async def execute(self, context: BriefContext) -> StockBrief | None:
        now = self._market_clock.now()
        brief = StockBrief(
            stock_id=context.stock_id,
            day=now.date(),
            status=BriefStatus.WRITING,
            language=self._language,
            model=self._model,
            claimed_at=now,
            window_first=context.window_first,
            window_last=context.window_last,
            price_change=context.price_change,
        )

        if await self._briefs.claim(brief, self._daily_stocks, now - self._claim_time):
            return brief

        if await self._briefs.find(brief.stock_id, brief.day) is None:
            raise BriefLimitReached("Today's new AI briefs are spent. They renew at midnight Taiwan time.")

        return None
