from datetime import time

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.model.market.article import Article
from a_domain.model.market.world_indicator import IndicatorReading
from a_domain.ports.ai.stock_brief_repository import IStockBriefRepository
from a_domain.ports.market.article_store import IArticleStore
from a_domain.ports.market.world_indicator_repository import IWorldIndicatorRepository
from a_domain.types.enums import MarketScope
from b_application.config.app_config import AppConfig


class WorldLookup:
    """
    What the site holds of the world, for the world page and the home page's block: each held indicator's newest
    reading beside the one before it, the written world briefs of the latest world.brief.shown_days days that have
    one, newest first, the newest world.shown kept world news items, and the Taipei time from which the site writes
    the day's brief, None while it writes none (AppConfig.world_brief_due_rule). It reads held data alone: no feed and
    no AI.
    """

    def __init__(
        self, indicators: IWorldIndicatorRepository, briefs: IStockBriefRepository, store: IArticleStore, config: AppConfig
    ) -> None:
        self._indicators = indicators
        self._briefs = briefs
        self._store = store
        self._shown_days = config.world.brief.shown_days
        self._shown = config.world.shown
        self._due_rule = config.world_brief_due_rule()

    async def execute(self) -> tuple[list[IndicatorReading], list[StockBrief], list[Article], time | None]:
        readings = await self._indicators.latest()
        briefs = await self._briefs.recent(MarketScope.WORLD.value, self._shown_days)
        news = await self._store.latest(MarketScope.WORLD.value, self._shown)

        return readings, briefs, news, self._due_rule.write_at if self._due_rule.on else None
