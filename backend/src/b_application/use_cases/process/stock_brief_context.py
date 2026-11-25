from collections.abc import Sequence

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.model.market.article import Article
from a_domain.model.market.stock import Stock
from a_domain.ports.ai.article_index import IArticleIndex
from a_domain.ports.market.article_store import IArticleStore
from a_domain.ports.market.price_provider import IPriceHistoryProvider
from a_domain.ports.market.taiwan_stock_provider import ITaiwanStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.ai.stock_brief import BriefContext, written_card
from a_domain.rules.fundamentals.stock_analysis import StockAnalysis
from a_domain.rules.trading.ranking import RankingHistory, latest_decision
from a_domain.rules.trading.ranking_standing import RankingStandingRule
from a_domain.types.enums import Feature
from a_domain.types.errors import RankingUnavailable
from b_application.config.app_config import AppConfig


class StockBriefContext:
    """
    Gathers what a stock's AI brief may rest on, from held data alone (BriefContextRule): the stock with its industry
    in the exchanges' company profiles, its daily bars of the window from the history the stock pages share, its
    financial analysis, what is said about it, and its standing in the monthly ranking at the latest decision session.
    What is said about it is searched for in the article store by meaning (BriefSearchRule): the articles of the
    window, those shortly before it and those that say what the company makes and sells. While the searches find
    nothing, because the stock has no indexed article or the index cannot be asked, which is logged, it is `articles`,
    what the stock page shows. The standing is left out where the site does not show the ranking to every viewer,
    because the brief is shown to every viewer of the stock page, and where the history holds no decision session.
    `cards` are the company's cards as the site holds them, newest first: where one is written, it says what the
    company is, so the brief's prompt holds its text and no search for what the company makes and sells is made. It
    asks no AI.
    """

    def __init__(
        self,
        stock_provider: ITaiwanStockProvider,
        ohlcv_provider: IPriceHistoryProvider,
        store: IArticleStore,
        index: IArticleIndex,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._stock_provider = stock_provider
        self._ohlcv_provider = ohlcv_provider
        self._store = store
        self._index = index
        self._market_clock = market_clock
        self._logger = logger
        self._history_days = config.analysis.history_days(config.stock_page.brief.window_sessions)
        self._ranking_shown = config.features.visibility(Feature.RANKING).shown_to(frozenset())
        self._decision_rule = config.decision_sessions_rule()
        self._standing_rule = RankingStandingRule(ranking_rule=config.ranking.ranking_rule())
        self._search_rule = config.stock_page.brief.search_rule(
            config.prompts.stock_brief_rise_query, config.prompts.stock_brief_fall_query, config.prompts.stock_brief_company_query
        )
        self._context_rule = config.stock_page.brief.context_rule()

    async def execute(
        self,
        stock: Stock,
        analysis: StockAnalysis,
        articles: list[Article],
        history: RankingHistory,
        cards: Sequence[StockBrief | None] = (),
    ) -> BriefContext:
        stock.industry = (await self._stock_provider.fetch_industries()).get(stock.stock_id, stock.industry)
        window = self._market_clock.history_window(self._history_days)
        bars = (await self._ohlcv_provider.fetch_history([stock], *window)).get(stock.stock_id, [])

        try:
            decision = latest_decision(self._decision_rule, history.bars.sessions) if self._ranking_shown else None
        except RankingUnavailable:
            decision = None

        standing = self._standing_rule.apply(history, *decision, [stock.stock_id])[stock.stock_id] if decision else None
        today = self._market_clock.today()
        retrieved: list[Article] = []

        try:
            for search in self._search_rule.apply(bars, today, card_held=written_card(cards) is not None):
                keys = await self._index.search(stock.stock_id, search.query, search.first, search.last, search.limit)
                kept = {article.key: article for article in await self._store.find(stock.stock_id, keys)}
                retrieved.extend(kept[key] for key in keys if key in kept)
        except Exception as error:
            self._logger.warning(
                f"Brief of {stock.stock_id}: the article index could not be searched: {type(error).__name__}: {error}"
            )
            retrieved = []

        return self._context_rule.apply(stock, bars, analysis, standing, articles, retrieved, today, cards)
