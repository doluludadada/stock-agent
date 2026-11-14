from itertools import groupby
from operator import attrgetter

from a_domain.ports.market.article_store import IArticleStore
from a_domain.ports.market.daily_close_archive import IDailyCloseArchive
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.errors import ListingUnavailableError
from b_application.config.app_config import AppConfig


class ArticleStoreBackfill:
    """
    `just backfill-articles`: every announcement of a listed stock and every TWSE news item naming one that the
    open-data archive holds of the last stock_page.article_store.retention_days, kept in the article store, one stock
    at a time. It answers how many articles that added or replaced, and every stock the store keeps articles of, whose
    vectors the command then brings up to date. It reaches no site: the archive already holds what it reads. Run again,
    it adds nothing. ListingUnavailableError during a listing outage.
    """

    def __init__(
        self,
        archive: IDailyCloseArchive,
        store: IArticleStore,
        stock_provider: IStockProvider,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._archive = archive
        self._store = store
        self._stock_provider = stock_provider
        self._market_clock = market_clock
        self._logger = logger
        self._retention = config.stock_page.article_store.retention()
        self._kept_rule = config.stock_page.article_store.kept_rule(config.audience.news_articles)

    async def execute(self) -> tuple[int, list[str]]:
        listed = {stock.stock_id for stock in await self._stock_provider.get_all()}

        if not listed:
            raise ListingUnavailableError("The TWSE and TPEX listings could not be loaded.")

        archived = await self._archive.archived_articles(self._market_clock.now() - self._retention)
        of_listed = sorted((article for article in archived if article.stock_id in listed), key=attrgetter("stock_id"))
        kept = 0

        for _, articles in groupby(of_listed, key=attrgetter("stock_id")):
            kept += await self._store.save([self._kept_rule.apply(article) for article in articles])

        self._logger.info(f"Article store: {kept} of the archive's {len(of_listed)} articles added or replaced.")

        return kept, await self._store.stock_ids()
