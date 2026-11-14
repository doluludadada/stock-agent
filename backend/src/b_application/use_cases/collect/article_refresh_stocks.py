from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.users_stocks import IUsersStocks
from b_application.config.app_config import AppConfig


class ArticleRefreshStocks:
    """
    The stocks whose news the Web API's timer fetches into the article store, so their articles accumulate whether or
    not anyone opens their pages: every stock a user holds or watches, in stock id order, at most
    stock_page.article_store.refresh_stocks. A mock account that follows the monthly ranking holds its stocks, so they
    are among them, and the timer computes no ranking and loads no daily history.
    """

    def __init__(self, users_stocks: IUsersStocks, config: AppConfig, logger: ILoggingProvider) -> None:
        self._users_stocks = users_stocks
        self._logger = logger
        self._limit = config.stock_page.article_store.refresh_stocks

    async def execute(self) -> list[str]:
        held_or_watched = sorted(await self._users_stocks.held_or_watched())
        chosen = held_or_watched[: self._limit]
        self._logger.info(
            f"Article store: reading the news of {len(chosen)} of the {len(held_or_watched)} stocks users hold or watch."
        )

        return chosen
