from datetime import timedelta

from a_domain.model.market.article import Article
from a_domain.ports.ai.article_index import IArticleIndex
from a_domain.ports.ai.stock_brief_repository import IStockBriefRepository
from a_domain.ports.market.article_store import IArticleStore
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.market.world_indicator_repository import IWorldIndicatorRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.ai.stock_brief import BriefContext
from a_domain.types.enums import MarketScope
from b_application.config.app_config import AppConfig


class WorldBriefContext:
    """
    Gathers what the day's world brief may rest on, from held data alone (WorldBriefContextRule), when the brief is
    due (WorldBriefDueRule): the held indicators' newest readings, and the kept world news of the window, searched for
    by meaning with prompts.world_brief_query in the article store, or its newest items while the query is empty, the
    search finds nothing or the index cannot be asked, which is logged. It also reads the listing, so that a sentence
    may link a listed stock a cited item names itself.

    None while no brief is due, so nothing is searched and no AI is asked: before world.brief.write_at of the Taipei
    day; while the site writes no world brief (AppConfig.world_brief_due_rule); once the day's brief is written or
    is being written; for world.brief.retry_minutes after a failed one was asked for. None too while the
    site holds neither a reading nor a world news item of the window. It asks no AI.
    """

    def __init__(
        self,
        indicators: IWorldIndicatorRepository,
        store: IArticleStore,
        index: IArticleIndex,
        briefs: IStockBriefRepository,
        stock_provider: IStockProvider,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._indicators = indicators
        self._store = store
        self._index = index
        self._briefs = briefs
        self._stock_provider = stock_provider
        self._market_clock = market_clock
        self._logger = logger
        self._due_rule = config.world_brief_due_rule()
        self._query = config.prompts.world_brief_query.strip()
        self._window = timedelta(hours=config.world.brief.window_hours)
        self._articles = config.world.brief.articles
        self._context_rule = config.world.brief.context_rule()

    async def execute(self) -> BriefContext | None:
        now = self._market_clock.now()
        world = MarketScope.WORLD.value

        if not self._due_rule.apply(await self._briefs.find(world, now.date()), now):
            return None

        newest = await self._store.latest(world, self._articles)
        retrieved: list[Article] = []

        try:
            keys = (
                await self._index.search(world, self._query, (now - self._window).date(), None, self._articles) if self._query else []
            )
            kept = {article.key: article for article in await self._store.find(world, keys)}
            retrieved = [kept[key] for key in keys if key in kept]
        except Exception as error:
            self._logger.warning(f"World brief: the article index could not be searched: {type(error).__name__}: {error}")

        listed = {stock.stock_id: stock.name or "" for stock in await self._stock_provider.get_all()}
        context = self._context_rule.apply(await self._indicators.latest(), newest, retrieved, listed, now)

        return context if context.facts else None
