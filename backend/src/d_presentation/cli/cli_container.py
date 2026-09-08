# backend/src/d_presentation/cli/cli_container.py

from dataclasses import dataclass

from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.notification_provider import INotificationProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import (
    ExecutionProvider,
    OrderMode,
    SystemEnvironment,
)
from b_application.factories.technical_strategy import create_technical_strategies
from b_application.pipeline import Pipeline
from b_application.schemas.config import AppConfig
from b_application.schemas.technical_strategies import TechnicalStrategies
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.collect.market_scanner import MarketScanner
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.composite_scorer import CompositeScorer
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.manual_buy import ManualBuy
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.use_cases.trade.watch_stocks import WatchStocks
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
from c_infrastructure.platforms.line.line_notification_adapter import (
    LineNotificationAdapter,
)
from c_infrastructure.system.config_loader import load_settings
from c_infrastructure.system.logger_service import LoggerService
from c_infrastructure.system.market_clock import TaiwanMarketClock
from c_infrastructure.trading.mock.mock_execution_provider import (
    MockExecutionProvider,
)


@dataclass(slots=True)
class CliRuntime:
    pipeline: Pipeline
    watch_stocks: WatchStocks
    manual_buy: ManualBuy
    config: AppConfig
    db: DatabaseConnector
    logger: ILoggingProvider

    async def shutdown(self) -> None:
        await self.db.close()


@dataclass(slots=True)
class ProviderDependencies:
    stock_provider: TaiwanStockProvider
    price_provider: CachedPriceProvider
    news_provider: NewsProvider
    social_media_provider: PttProvider
    ai_provider: IAiProvider
    knowledge_repository: ChromaRepositoryAdapter
    signal_repository: SignalRepository
    watchlist_repository: WatchlistRepository
    execution_provider: IExecutionProvider
    notification_provider: INotificationProvider | None


@dataclass(slots=True)
class CollectUseCases:
    market_scanner: MarketScanner
    data_collector: MarketDataCollector
    buzz_scanner: BuzzScanner
    news_feed: NewsFeed


@dataclass(slots=True)
class ProcessUseCases:
    ai_analyser: AiAnalyser
    technical_filter: TechnicalFilter
    technical_strategies: TechnicalStrategies
    composite_scorer: CompositeScorer


@dataclass(slots=True)
class TradingUseCases:
    account_loader: AccountLoader
    account_risk_check: AccountRiskCheck
    watch_stocks: WatchStocks
    manual_buy: ManualBuy
    signals: Signals
    order_execution: OrderExecution
    reporting: Reporting


def validate_trading_environment(
    config: AppConfig,
) -> None:
    """
    DEV must never use a real execution provider.

    OrderMode.DISABLED is still allowed in DEV.
    """
    if config.environment != SystemEnvironment.DEV:
        return

    if config.trading.execution_provider != ExecutionProvider.MOCK:
        raise ValueError("DEV environment requires MockExecutionProvider")

    if config.trading.order_mode == OrderMode.LIVE:
        raise ValueError("DEV environment cannot use LIVE order mode")


def create_ai_provider(
    config: AppConfig,
    logger: ILoggingProvider,
) -> IAiProvider:
    web_search_provider = None

    if config.tavily.api_key:
        web_search_provider = TavilySearchAdapter(
            config=config,
            logger=logger,
        )

    return AiAdapterFactory(
        config=config,
        logger=logger,
        web_search_provider=web_search_provider,
    ).create_adapter()


def create_execution_provider(
    config: AppConfig,
    db: DatabaseConnector,
    logger: ILoggingProvider,
) -> IExecutionProvider:
    if config.trading.execution_provider != ExecutionProvider.MOCK:
        raise NotImplementedError(f"Execution provider is not wired yet: {config.trading.execution_provider.value}")

    return MockExecutionProvider(
        db=db,
        config=config,
        logger=logger,
    )


def create_notification_provider(
    config: AppConfig,
    logger: ILoggingProvider,
) -> INotificationProvider | None:
    if not config.notifications.enabled:
        return None

    return LineNotificationAdapter(
        config=config,
        logger=logger,
    )


async def build_provider_dependencies(
    config: AppConfig,
    db: DatabaseConnector,
    logger: ILoggingProvider,
    market_clock: TaiwanMarketClock,
) -> ProviderDependencies:
    stock_provider = TaiwanStockProvider(
        logger=logger,
    )
    price_provider = CachedPriceProvider(
        price_provider=YahooFinanceProvider(logger=logger),
        db=db,
        logger=logger,
        market_clock=market_clock,
    )
    knowledge_repository = ChromaRepositoryAdapter(
        config=config,
        logger=logger,
    )
    await knowledge_repository.init()

    return ProviderDependencies(
        stock_provider=stock_provider,
        price_provider=price_provider,
        news_provider=NewsProvider(config=config, logger=logger),
        social_media_provider=PttProvider(
            config=config,
            logger=logger,
            stock_provider=stock_provider,
        ),
        ai_provider=create_ai_provider(config, logger),
        knowledge_repository=knowledge_repository,
        signal_repository=SignalRepository(db=db, logger=logger),
        watchlist_repository=WatchlistRepository(
            db=db,
            logger=logger,
            market_clock=market_clock,
        ),
        execution_provider=create_execution_provider(
            config,
            db,
            logger,
        ),
        notification_provider=create_notification_provider(
            config,
            logger,
        ),
    )


def build_collect_use_cases(
    config: AppConfig,
    logger: ILoggingProvider,
    market_clock: TaiwanMarketClock,
    dependencies: ProviderDependencies,
) -> CollectUseCases:
    return CollectUseCases(
        market_scanner=MarketScanner(
            stock_provider=dependencies.stock_provider,
            watchlist_repository=dependencies.watchlist_repository,
            logger=logger,
        ),
        data_collector=MarketDataCollector(
            ohlcv_provider=dependencies.price_provider,
            market_clock=market_clock,
            config=config,
            logger=logger,
        ),
        buzz_scanner=BuzzScanner(
            social_media_provider=dependencies.social_media_provider,
            stock_provider=dependencies.stock_provider,
            logger=logger,
            config=config,
        ),
        news_feed=NewsFeed(
            news_provider=dependencies.news_provider,
            config=config,
            logger=logger,
        ),
    )


def build_process_use_cases(
    config: AppConfig,
    logger: ILoggingProvider,
    dependencies: ProviderDependencies,
) -> ProcessUseCases:
    return ProcessUseCases(
        ai_analyser=AiAnalyser(
            ai_provider=dependencies.ai_provider,
            knowledge_repository=dependencies.knowledge_repository,
            config=config,
            logger=logger,
        ),
        technical_filter=TechnicalFilter(
            logger=logger,
        ),
        technical_strategies=create_technical_strategies(
            config,
        ),
        composite_scorer=CompositeScorer(
            config=config,
            logger=logger,
        ),
    )


def build_trading_use_cases(
    config: AppConfig,
    logger: ILoggingProvider,
    market_clock: TaiwanMarketClock,
    dependencies: ProviderDependencies,
) -> TradingUseCases:
    account_loader = AccountLoader(
        execution_provider=dependencies.execution_provider,
        stock_provider=dependencies.stock_provider,
        logger=logger,
    )
    order_execution = OrderExecution(
        execution_provider=dependencies.execution_provider,
        market_clock=market_clock,
        logger=logger,
    )
    manual_buy = ManualBuy(
        account_loader=account_loader,
        signal_repository=dependencies.signal_repository,
        order_execution=order_execution,
        config=config,
        logger=logger,
    )

    return TradingUseCases(
        account_loader=account_loader,
        account_risk_check=AccountRiskCheck(
            price_provider=dependencies.price_provider,
            config=config,
            logger=logger,
        ),
        watch_stocks=WatchStocks(
            watchlist_repository=dependencies.watchlist_repository,
            logger=logger,
        ),
        manual_buy=manual_buy,
        signals=Signals(
            signal_repository=dependencies.signal_repository,
            config=config,
            logger=logger,
        ),
        order_execution=order_execution,
        reporting=Reporting(
            notification_provider=dependencies.notification_provider,
            config=config,
            logger=logger,
        ),
    )


def build_pipeline(
    collect: CollectUseCases,
    process: ProcessUseCases,
    trading: TradingUseCases,
    logger: ILoggingProvider,
) -> Pipeline:
    return Pipeline(
        account_loader=trading.account_loader,
        account_risk_check=trading.account_risk_check,
        market_scanner=collect.market_scanner,
        data_collector=collect.data_collector,
        buzz_scanner=collect.buzz_scanner,
        news=collect.news_feed,
        ai=process.ai_analyser,
        technical_filter=process.technical_filter,
        technical_strategies=process.technical_strategies,
        composite_scorer=process.composite_scorer,
        watch_stocks=trading.watch_stocks,
        signals=trading.signals,
        order_execution=trading.order_execution,
        reporting=trading.reporting,
        logger=logger,
    )


async def build_cli_orchestrator() -> CliRuntime:
    config = load_settings()
    validate_trading_environment(config)

    logger = LoggerService(
        level=config.behavior.log_level,
    )
    market_clock = TaiwanMarketClock()

    db = DatabaseConnector(
        config=config,
        logger=logger,
    )
    await db.init_db()

    dependencies = await build_provider_dependencies(
        config=config,
        db=db,
        logger=logger,
        market_clock=market_clock,
    )
    collect = build_collect_use_cases(
        config,
        logger,
        market_clock,
        dependencies,
    )
    process = build_process_use_cases(
        config,
        logger,
        dependencies,
    )
    trading = build_trading_use_cases(
        config,
        logger,
        market_clock,
        dependencies,
    )

    return CliRuntime(
        pipeline=build_pipeline(
            collect,
            process,
            trading,
            logger,
        ),
        watch_stocks=trading.watch_stocks,
        manual_buy=trading.manual_buy,
        config=config,
        db=db,
        logger=logger,
    )
