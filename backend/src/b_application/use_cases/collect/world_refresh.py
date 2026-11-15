from a_domain.ports.ai.article_index import IArticleIndex
from a_domain.ports.market.article_store import IArticleStore
from a_domain.ports.market.world_feed import IWorldFeed
from a_domain.ports.market.world_indicator_repository import IWorldIndicatorRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MarketScope
from b_application.config.app_config import AppConfig


class WorldRefresh:
    """
    Reads the world into what the site holds, and says how many world news items it added or replaced, how many it
    embedded and how many indicator readings are new: the items the world news feeds list now, kept in the article
    store under MarketScope.WORLD with the summary each feed gives (KeptArticleRule), within world.retention_days and
    world.max_items, then their vectors brought in line with the kept items, so a lost index fills again here; and the
    readings the indicators' tables list. An item whose feed gave no publication time is left out: the page shows no
    time it cannot stand behind. Run again, it adds nothing. `feed` is None on a site that reads no world feed, which
    reads nothing. The store keeps the items when the embedding model cannot be opened or the index refuses: that is
    logged, and the next round tries again. It asks no AI.
    """

    def __init__(
        self,
        feed: IWorldFeed | None,
        store: IArticleStore,
        index: IArticleIndex,
        indicators: IWorldIndicatorRepository,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._feed = feed
        self._store = store
        self._index = index
        self._indicators = indicators
        self._logger = logger
        self._max_items = config.world.max_items
        self._kept_rule = config.stock_page.article_store.kept_rule(config.audience.news_articles)

    async def execute(self) -> tuple[int, int, int]:
        if self._feed is None:
            return 0, 0, 0

        world = MarketScope.WORLD.value
        items = [self._kept_rule.apply(item) for item in await self._feed.fetch_news() if item.publication_known]
        kept = await self._store.save(items)
        embedded = 0

        try:
            embedded = await self._index.sync(world, await self._store.latest(world, self._max_items))
        except Exception as error:
            self._logger.warning(f"The world news' index was not brought up to date: {type(error).__name__}: {error}")

        readings = await self._indicators.save(await self._feed.fetch_indicators())
        self._logger.info(f"World: {kept} news items kept, {embedded} embedded, {readings} indicator readings new.")

        return kept, embedded, readings
