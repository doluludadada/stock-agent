# backend/src/d_presentation/cli/cli_container.py

from b_application.pipeline import Pipeline
from b_application.use_cases.collect.market_data import MarketData
from b_application.use_cases.collect.market_scan import MarketScan
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.collect.stock_selector import StockSelector
from b_application.use_cases.collect.watchlist import Watchlist
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.workflow import WorkflowOrchestrator
from c_infrastructure.ai_models.factory import AiAdapterFactory
from c_infrastructure.database.chroma.chroma_repository import ChromaRepositoryAdapter
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.signal_repository import SignalRepository
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.feed.news_provider import NewsProvider
from c_infrastructure.feed.ptt_provider import PttProvider
from c_infrastructure.feed.tavily_provider import TavilySearchAdapter
from c_infrastructure.market.cached_price_provider import CachedPriceProvider
from c_infrastructure.market.indicator_provider import IndicatorProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider
from c_infrastructure.platforms.line.line_notification_adapter import LineNotificationAdapter
from c_infrastructure.system.config_loader import load_settings
from c_infrastructure.system.logger_service import LoggerService
from c_infrastructure.system.market_clock import TaiwanMarketClock
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider


async def build_cli_orchestrator() -> WorkflowOrchestrator:
    config = load_settings()
    logger = LoggerService(level=config.behavior.log_level)
    market_clock = TaiwanMarketClock()

    db = DatabaseConnector(config, logger)
    await db.init_db()

    watchlist_repo = WatchlistRepository(
        db=db,
        logger=logger,
        market_clock=market_clock,
    )
    signal_repo = SignalRepository(db, logger)

    knowledge_db = ChromaRepositoryAdapter(config, logger)
    await knowledge_db.init()

    stock_provider = TaiwanStockProvider(logger)
    yahoo_provider = YahooFinanceProvider(logger)
    price_provider = CachedPriceProvider(
        price_provider=yahoo_provider,
        db=db,
        logger=logger,
        market_clock=market_clock,
    )
    indicator_provider = IndicatorProvider(config)
    news_provider = NewsProvider(config, logger)
    social_provider = PttProvider(config=config, logger=logger, stock_provider=stock_provider)
    web_search_provider = TavilySearchAdapter(config, logger) if config.tavily.api_key else None

    ai_provider = AiAdapterFactory(
        config=config,
        logger=logger,
        web_search_provider=web_search_provider,
    ).create_adapter()

    notification_provider = LineNotificationAdapter(config=config, logger=logger)

    execution_provider = MockExecutionProvider(
        db=db,
        config=config,
        logger=logger,
    )

    watchlist = Watchlist(
        stock_provider=stock_provider,
        price_provider=price_provider,
        indicator_provider=indicator_provider,
        watchlist_repo=watchlist_repo,
        logger=logger,
        config=config,
        market_clock=market_clock,
    )

    market_scan = MarketScan(
        social_media_provider=social_provider,
        watchlist_repo=watchlist_repo,
        stock_provider=stock_provider,
        logger=logger,
        config=config,
    )

    account_loader = AccountLoader(
        execution_provider=execution_provider,
        stock_provider=stock_provider,
        logger=logger,
    )
    account_risk_check = AccountRiskCheck(
        price_provider=price_provider,
        config=config,
        logger=logger,
    )
    stock_selector = StockSelector(
        watchlist_repo=watchlist_repo,
        stock_provider=stock_provider,
        logger=logger,
    )
    market_data = MarketData(
        price_provider=price_provider,
        logger=logger,
        config=config,
        market_clock=market_clock,
    )
    technical_filter = TechnicalFilter(
        indicator_provider=indicator_provider,
        config=config,
        logger=logger,
    )
    news_feed = NewsFeed(
        news_provider=news_provider,
        logger=logger,
        config=config,
    )
    ai_analyser = AiAnalyser(
        ai_provider=ai_provider,
        knowledge_repo=knowledge_db,
        config=config,
        logger=logger,
    )
    signals = Signals(
        signal_repository=signal_repo,
        knowledge_repository=knowledge_db,
        config=config,
        logger=logger,
    )
    order_execution = OrderExecution(
        execution_provider=execution_provider,
        logger=logger,
    )
    reporting = Reporting(
        notification_provider=notification_provider,
        config=config,
        logger=logger,
    )

    pipeline = Pipeline(
        account_loader=account_loader,
        account_risk_check=account_risk_check,
        stock_selector=stock_selector,
        market_data=market_data,
        technical_filter=technical_filter,
        news_feed=news_feed,
        ai_analyser=ai_analyser,
        signals=signals,
        order_execution=order_execution,
        reporting=reporting,
        logger=logger,
    )

    return WorkflowOrchestrator(
        watchlist=watchlist,
        market_scan=market_scan,
        intraday_pipeline=pipeline,
        logger=logger,
        db=db,
    )
