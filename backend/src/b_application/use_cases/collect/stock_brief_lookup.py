from datetime import timedelta

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.ports.ai.stock_brief_repository import IStockBriefRepository
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import BriefStatus
from b_application.config.app_config import AppConfig


class StockBriefLookup:
    """
    The stock page's AI brief as the site holds it, with no AI call: the stock's brief of today in Taipei if a viewer
    asked for one, its newest written brief of an earlier day, which the page shows while today's is being written or
    after it failed, and how many more stocks may get a new brief today (stock_page.brief.daily_stocks). A brief still
    being written stock_page.brief.claim_minutes after its claim was left behind by a stopped server: it is answered
    as failed, so the page offers to ask again, and the next request takes it over.
    """

    def __init__(self, briefs: IStockBriefRepository, market_clock: IMarketClock, config: AppConfig) -> None:
        self._briefs = briefs
        self._market_clock = market_clock
        self._daily_stocks = config.stock_page.brief.daily_stocks
        self._claim_time = timedelta(minutes=config.stock_page.brief.claim_minutes)

    async def execute(self, stock_id: str) -> tuple[StockBrief | None, StockBrief | None, int]:
        now = self._market_clock.now()
        today = await self._briefs.find(stock_id, now.date())
        previous = await self._briefs.latest_written(stock_id, now.date())
        left = max(0, self._daily_stocks - await self._briefs.claimed_stocks(now.date()))

        if today is not None and today.status == BriefStatus.WRITING and today.claimed_at < now - self._claim_time:
            today.fail()

        return today, previous, left
