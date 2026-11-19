from datetime import timedelta

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.ports.ai.stock_brief_repository import IStockBriefRepository
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import BriefKind
from b_application.config.app_config import AppConfig


class BriefLookup:
    """
    What the site holds of one of its AI texts of `kind` (BriefKind), with no AI call: the stock's text of today in
    Taipei if one was claimed, its newest written text of an earlier day, which a page shows while today's is being
    written or after it failed, and how many more stocks may get a new one today (stock_page.brief.daily_stocks for
    the daily brief, stock_page.card.daily_stocks for the company card, one for the world brief). A text still being
    written stock_page.brief.claim_minutes after its claim was left behind by a stopped server: it is answered as
    failed, so the page offers to ask again, and the next request takes it over (DailyStockBrief).
    """

    def __init__(
        self, briefs: IStockBriefRepository, market_clock: IMarketClock, config: AppConfig, kind: BriefKind = BriefKind.MOVEMENT
    ) -> None:
        self._briefs = briefs
        self._market_clock = market_clock
        self._claim_time = timedelta(minutes=config.stock_page.brief.claim_minutes)
        _, _, self._daily_stocks, _ = config.brief_writing(kind)

    async def execute(self, stock_id: str) -> tuple[StockBrief | None, StockBrief | None, int]:
        now = self._market_clock.now()
        today = await self._briefs.find(stock_id, now.date())
        previous = await self._briefs.latest_written(stock_id, now.date())
        left = max(0, self._daily_stocks - await self._briefs.claimed_stocks(now.date()))

        if today is not None and today.abandoned(now - self._claim_time):
            today.fail()

        return today, previous, left
