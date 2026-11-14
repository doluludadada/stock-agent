from a_domain.ports.ai.article_index import IArticleIndex
from a_domain.ports.market.article_store import IArticleStore
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.app_config import AppConfig


class ArticleIndexer:
    """
    Brings one stock's vectors in line with the articles the article store keeps of it, and says how many articles it
    embedded: only those that are new or whose text changed, so a stock whose articles did not change costs no
    embedding. The vectors are computed from the store alone, so an index that was lost fills again here. It never
    fails its operation: when the embedding model cannot be opened or the index refuses, it logs that and answers 0,
    the store keeps the articles, and the next call tries again.
    """

    def __init__(self, store: IArticleStore, index: IArticleIndex, config: AppConfig, logger: ILoggingProvider) -> None:
        self._store = store
        self._index = index
        self._logger = logger
        self._max_per_stock = config.stock_page.article_store.max_per_stock

    async def execute(self, stock_id: str) -> int:
        try:
            return await self._index.sync(stock_id, await self._store.latest(stock_id, self._max_per_stock))
        except Exception as error:
            self._logger.warning(f"The article index of {stock_id} was not brought up to date: {type(error).__name__}: {error}")
            return 0
