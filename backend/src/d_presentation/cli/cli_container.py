from dataclasses import dataclass

from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.pipeline import AnalysisPipeline
from b_application.schemas.config import AppConfig
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.market_scanner import MarketScanner
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.workflow import TradingWorkflow
from c_infrastructure.ai_models.factory import AiAdapterFactory
from c_infrastructure.database.chroma.chroma_repository import ChromaRepositoryAdapter
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.signal_repository import SignalRepository
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.feed.news_provider import NewsProvider
from c_infrastructure.feed.ptt_provider import PttProvider
from c_infrastructure.feed.tavily_provider import TavilySearchAdapter
from c_infrastructure.market.cached_price_provider import CachedPriceProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider
from c_infrastructure.platforms.line.line_notification_adapter import LineNotificationAdapter
from c_infrastructure.system.config_loader import load_settings
from c_infrastructure.system.logger_service import LoggerService
from c_infrastructure.system.market_clock import TaiwanMarketClock
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider


@dataclass(slots=True)
class CliRuntime:
    workflow: TradingWorkflow
    config: AppConfig
    db: DatabaseConnector
    logger: ILoggingProvider

    async def shutdown(self) -> None:
        await self.db.close()


async def build_cli_orchestrator() -> CliRuntime:
    config = load_settings()
    logger = LoggerService(level=config.behavior.log_level)
    market_clock = TaiwanMarketClock()

    db = DatabaseConnector(config=config, logger=logger)
    await db.init_db()

    stock_provider = TaiwanStockProvider(logger=logger)
    price_provider = CachedPriceProvider(
        price_provider=YahooFinanceProvider(logger=logger),
        db=db,
        logger=logger,
        market_clock=market_clock,
    )
    news_provider = NewsProvider(config=config, logger=logger)
    social_media_provider = PttProvider(
        config=config,
        logger=logger,
        stock_provider=stock_provider,
    )
    web_search_provider = TavilySearchAdapter(config=config, logger=logger) if config.tavily.api_key else None

    ai_provider = AiAdapterFactory(
        config=config,
        logger=logger,
        web_search_provider=web_search_provider,
    ).create_adapter()
    knowledge_repository = ChromaRepositoryAdapter(config=config, logger=logger)
    await knowledge_repository.init()

    signal_repository = SignalRepository(db=db, logger=logger)
    watchlist_repository = WatchlistRepository(
        db=db,
        logger=logger,
        market_clock=market_clock,
    )
    execution_provider = MockExecutionProvider(
        db=db,
        config=config,
        logger=logger,
    )
    notification_provider = LineNotificationAdapter(config=config, logger=logger) if config.notifications.enabled else None

    market_scanner = MarketScanner(
        stock_provider=stock_provider,
        Ohlcv_provider=price_provider,
        market_clock=market_clock,
        config=config,
        logger=logger,
    )
    buzz_scanner = BuzzScanner(
        social_media_provider=social_media_provider,
        stock_provider=stock_provider,
        logger=logger,
        config=config,
    )
    news_feed = NewsFeed(
        news_provider=news_provider,
        config=config,
        logger=logger,
    )
    ai_analyser = AiAnalyser(
        ai_provider=ai_provider,
        knowledge_repository=knowledge_repository,
        config=config,
        logger=logger,
    )
    technical_filter = TechnicalFilter(config=config, logger=logger)
    signals = Signals(
        signal_repository=signal_repository,
        knowledge_repository=knowledge_repository,
        config=config,
        logger=logger,
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
    order_execution = OrderExecution(
        execution_provider=execution_provider,
        market_clock=market_clock,
        logger=logger,
    )
    reporting = Reporting(
        notification_provider=notification_provider,
        config=config,
        logger=logger,
    )
    analysis_pipeline = AnalysisPipeline(
        news_feed=news_feed,
        ai_analyser=ai_analyser,
        logger=logger,
    )
    workflow = TradingWorkflow(
        market_scanner=market_scanner,
        buzz_scanner=buzz_scanner,
        stock_provider=stock_provider,
        watchlist_repository=watchlist_repository,
        account_loader=account_loader,
        account_risk_check=account_risk_check,
        technical_filter=technical_filter,
        analysis_pipeline=analysis_pipeline,
        signals=signals,
        order_execution=order_execution,
        reporting=reporting,
        logger=logger,
    )

    return CliRuntime(
        workflow=workflow,
        config=config,
        db=db,
        logger=logger,
    )
