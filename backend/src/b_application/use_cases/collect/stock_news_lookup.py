from a_domain.model.market.article import Article
from a_domain.ports.market.article_store import IArticleStore
from a_domain.ports.market.daily_close_archive import IDailyCloseArchive
from a_domain.ports.market.stock_feed import IStockFeed
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.types.errors import ListingUnavailableError
from b_application.config.app_config import AppConfig


class StockNewsLookup:
    """
    What is said about one listed stock, for its page, newest first. It reads what there is to read now: the material
    information the company announced and the TWSE news naming it that the open-data archive holds of the last
    analysis.material_information_days, and, on a site that may read them, the news sites' articles and the board's
    posts as the stock feed holds them (IStockFeed), at most analysis.article_fetch_limit of each. A fed article its
    source gave no publication time is stamped with the moment it was fetched (Yahoo's listing gives none), so it is
    left out: the page shows no time it cannot stand behind. It keeps those in the article store (IArticleStore), each
    with the text the site may hold of it (KeptArticleRule), and answers the stock's newest
    stock_page.article_store.shown kept articles, so the page also lists what the sources no longer serve; an annual
    report's sections are no news and are left out (IArticleStore.latest). `feed` is
    None on a site without news articles (public), which reads the archive alone. Only a listed stock is asked for, so
    no made-up code reaches a news site: None for any other, and ListingUnavailableError during a listing outage.
    """

    def __init__(
        self,
        archive: IDailyCloseArchive,
        feed: IStockFeed | None,
        store: IArticleStore,
        stock_provider: IStockProvider,
        config: AppConfig,
    ) -> None:
        self._archive = archive
        self._feed = feed
        self._store = store
        self._stock_provider = stock_provider
        self._limit = config.analysis.article_fetch_limit
        self._shown = config.stock_page.article_store.shown
        self._kept_rule = config.stock_page.article_store.kept_rule(config.audience.news_articles)

    async def execute(self, stock_id: str) -> list[Article] | None:
        listed = {stock.stock_id for stock in await self._stock_provider.get_all()}

        if not listed:
            raise ListingUnavailableError("The TWSE and TPEX listings could not be loaded.")

        if stock_id not in listed:
            return None

        articles = await self._archive.fetch_news(stock_id, self._limit)

        if self._feed is not None:
            fed = await self._feed.fetch(stock_id, self._limit)
            articles = articles + [article for article in fed if article.publication_known]

        await self._store.save([self._kept_rule.apply(article) for article in articles])

        return await self._store.latest(stock_id, self._shown)
