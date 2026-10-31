from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.sentiment_classifier import ISentimentClassifier
from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.chat.platform_provider import IPlatformProvider
from a_domain.ports.market.fundamentals_provider import IFundamentalsProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.notification_provider import INotificationProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import ExecutionProvider, OrderMode, SystemEnvironment
from b_application.config.app_config import AppConfig
from b_application.pipeline import ChatSteps, CollectSteps, Pipeline, ProcessSteps, TradingSteps, ValuationSteps
from b_application.use_cases.chat.ai_processor import AiProcessor
from b_application.use_cases.chat.context_loader import ContextLoader
from b_application.use_cases.chat.dispatcher import Dispatcher
from b_application.use_cases.chat.state_manager import StateManager
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.fundamentals_feed import FundamentalsFeed
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.collect.market_scanner import MarketScanner
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.composite_scorer import CompositeScorer
from b_application.use_cases.process.sentiment_analyser import SentimentAnalyser
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.process.valuation_explainer import ValuationExplainer
from b_application.use_cases.ship.decision_memory import DecisionMemory
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.run_history import RunHistory
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_history import AccountHistory
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.manual_signal import ManualSignal
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.use_cases.trade.watch_stocks import WatchStocks
from c_infrastructure.ai_models.factory import AiAdapterFactory
from c_infrastructure.ai_models.sentiment_classifier import AiSentimentClassifier
from c_infrastructure.database.chroma.chroma_repository import ChromaRepositoryAdapter
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.trading_journal import TradingJournal
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.feed.news_provider import NewsProvider
from c_infrastructure.feed.ptt_provider import PttProvider
from c_infrastructure.feed.tavily_provider import TavilySearchAdapter
from c_infrastructure.market.cached_price_provider import CachedPriceProvider
from c_infrastructure.market.mis_quote_provider import MisQuoteProvider
from c_infrastructure.market.mops_fundamentals_provider import MopsFundamentalsProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider
from c_infrastructure.platforms.line.line_adapter import LinePlatformAdapter
from c_infrastructure.platforms.line.line_handler import LineWebhookHandler
from c_infrastructure.platforms.line.line_notification_adapter import LineNotificationAdapter
from c_infrastructure.platforms.line.line_security import LineSecurityService
from c_infrastructure.system.chat_styler_service import ChatStylerService
from c_infrastructure.system.config_loader import load_settings
from c_infrastructure.system.logger_service import LoggerService
from c_infrastructure.system.market_clock import TaiwanMarketClock
from c_infrastructure.technical.yaml_technical_settings_repository import YamlTechnicalSettingsRepository
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider


@dataclass(slots=True)
class Runtime:
    """
    The one object graph the CLI and the Web API run on. open_runtime() builds it from the real adapters;
    compose_runtime() wires the same graph over any ports, so tests and the order-gate check run it over fakes.
    """

    pipeline: Pipeline
    watch_stocks: WatchStocks
    account_history: AccountHistory
    stock_provider: IStockProvider
    journal: ITradingJournal
    watchlist_repository: IWatchlistRepository
    technical_settings_repository: ITechnicalSettingsRepository
    config: AppConfig
    logger: ILoggingProvider


@dataclass(slots=True)
class ProviderDependencies:
    stock_provider: TaiwanStockProvider
    price_provider: CachedPriceProvider
    fundamentals_provider: IFundamentalsProvider
    news_provider: NewsProvider
    social_media_provider: PttProvider
    ai_provider: IAiProvider
    sentiment_classifier: ISentimentClassifier
    knowledge_repository: ChromaRepositoryAdapter
    conversation_repository: IConversationRepository
    journal: ITradingJournal
    watchlist_repository: WatchlistRepository
    technical_settings_repository: ITechnicalSettingsRepository
    execution_provider: IExecutionProvider
    notification_provider: INotificationProvider | None
    platform_provider: IPlatformProvider | None


class TradingSetupError(RuntimeError):
    """The trading settings or the broker login do not let the CLI or the Web API start. The message says what to change."""


def validate_trading_environment(config: AppConfig) -> None:
    """
    Refuses a trading setup that could send an order nobody meant to send, before any broker is contacted.

    - DEV uses the mock broker only.
    - mock_only order mode needs the mock broker.
    - live order mode needs environment live and the Shioaji broker.
    - The Shioaji broker needs its credentials.
    Order mode disabled never orders, so outside DEV it may read a real Shioaji account.
    """
    environment, provider, mode = config.environment, config.trading.execution_provider, config.trading.order_mode

    if environment == SystemEnvironment.DEV and provider != ExecutionProvider.MOCK:
        raise TradingSetupError("DEV environment requires MockExecutionProvider")

    if mode == OrderMode.MOCK_ONLY and provider != ExecutionProvider.MOCK:
        raise TradingSetupError(
            f"order_mode mock_only needs execution_provider mock, not {provider.value}. "
            f"Use order_mode disabled to read the {provider.value} account without ordering"
        )

    if mode == OrderMode.LIVE and (environment != SystemEnvironment.LIVE or provider != ExecutionProvider.SHIOAJI):
        raise TradingSetupError(
            f"order_mode live needs environment live and execution_provider shioaji, not {environment.value} and {provider.value}"
        )

    if provider == ExecutionProvider.SHIOAJI and (missing := config.shioaji.missing_credentials()):
        raise TradingSetupError(f"execution_provider shioaji needs {', '.join(missing)} in the environment or .env")


def create_ai_provider(config: AppConfig, logger: ILoggingProvider) -> IAiProvider:
    web_search_provider = None

    if config.tavily.api_key:
        web_search_provider = TavilySearchAdapter(config=config, logger=logger)

    factory = AiAdapterFactory(config=config, logger=logger, web_search_provider=web_search_provider)

    return factory.create_adapter()


async def create_execution_provider(config: AppConfig, db: DatabaseConnector, logger: ILoggingProvider) -> IExecutionProvider:
    if config.trading.execution_provider == ExecutionProvider.MOCK:
        return MockExecutionProvider(db=db, config=config, logger=logger)

    # Imported only for Shioaji: importing shioaji creates shioaji.log in the working directory and logs a warning.
    from c_infrastructure.trading.shioaji.execution_provider import ShioajiExecutionProvider

    broker = "simulation" if config.shioaji.simulation else "production"

    try:
        provider = await ShioajiExecutionProvider.connect(config, logger)

    except Exception as error:
        raise TradingSetupError(f"Shioaji {broker} login failed: {type(error).__name__}: {error}") from error

    logger.info(f"Logged in to Shioaji {broker}. Order mode: {config.trading.order_mode.value}")

    return provider


def create_platform_provider(config: AppConfig, logger: ILoggingProvider) -> IPlatformProvider | None:
    """The LINE chat platform, or None while LINE_CHANNEL_ACCESS_TOKEN is unset: the adapter refuses to build without it."""
    if not config.line.channel_access_token:
        return None

    return LinePlatformAdapter(config=config, logger=logger)


def create_notification_provider(config: AppConfig, logger: ILoggingProvider) -> INotificationProvider | None:
    if not config.notifications.enabled:
        return None

    return LineNotificationAdapter(config=config, logger=logger)


async def build_provider_dependencies(
    config: AppConfig, db: DatabaseConnector, logger: ILoggingProvider, market_clock: TaiwanMarketClock
) -> ProviderDependencies:
    stock_provider = TaiwanStockProvider(exchange=config.sources.exchange, logger=logger)
    yahoo_provider = YahooFinanceProvider(logger=logger)

    price_provider = CachedPriceProvider(
        history_provider=yahoo_provider,
        quote_provider=MisQuoteProvider(exchange=config.sources.exchange, logger=logger),
        db=db,
        logger=logger,
        market_clock=market_clock,
    )

    knowledge_repository = ChromaRepositoryAdapter(config=config, logger=logger)
    await knowledge_repository.init()

    technical_path = config.project_root / "config" / "technical.yaml"
    ai_provider = create_ai_provider(config, logger)

    return ProviderDependencies(
        stock_provider=stock_provider,
        price_provider=price_provider,
        fundamentals_provider=MopsFundamentalsProvider(db=db, market_clock=market_clock, mops=config.sources.mops, logger=logger),
        news_provider=NewsProvider(config=config, logger=logger),
        social_media_provider=PttProvider(config=config, logger=logger, stock_provider=stock_provider),
        ai_provider=ai_provider,
        sentiment_classifier=AiSentimentClassifier(ai_provider=ai_provider, db=db, config=config, logger=logger),
        knowledge_repository=knowledge_repository,
        conversation_repository=knowledge_repository,
        journal=TradingJournal(db=db),
        watchlist_repository=WatchlistRepository(db=db, logger=logger, market_clock=market_clock),
        technical_settings_repository=YamlTechnicalSettingsRepository(technical_path),
        execution_provider=await create_execution_provider(config, db, logger),
        notification_provider=create_notification_provider(config, logger),
        platform_provider=create_platform_provider(config, logger),
    )


def build_collect_steps(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> CollectSteps:
    market_scanner = MarketScanner(
        stock_provider=dependencies.stock_provider, watchlist_repository=dependencies.watchlist_repository, logger=logger
    )

    data_collector = MarketDataCollector(
        ohlcv_provider=dependencies.price_provider, market_clock=market_clock, config=config, logger=logger
    )

    buzz_scanner = BuzzScanner(
        social_media_provider=dependencies.social_media_provider,
        stock_provider=dependencies.stock_provider,
        logger=logger,
        config=config,
    )

    news_feed = NewsFeed(news_provider=dependencies.news_provider, config=config, logger=logger)

    return CollectSteps(market_scanner, data_collector, buzz_scanner, news_feed)


def build_process_steps(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> ProcessSteps:
    ai_analyser = AiAnalyser(
        ai_provider=dependencies.ai_provider,
        knowledge_repository=dependencies.knowledge_repository,
        market_clock=market_clock,
        config=config,
        logger=logger,
    )

    return ProcessSteps(
        ai_analyser=ai_analyser,
        technical_filter=TechnicalFilter(logger=logger),
        composite_scorer=CompositeScorer(config=config, logger=logger),
        sentiment_analyser=SentimentAnalyser(classifier=dependencies.sentiment_classifier, logger=logger),
    )


def build_trading_steps(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> TradingSteps:
    account_loader = AccountLoader(
        execution_provider=dependencies.execution_provider,
        stock_provider=dependencies.stock_provider,
        journal=dependencies.journal,
        market_clock=market_clock,
        logger=logger,
    )

    order_execution = OrderExecution(
        execution_provider=dependencies.execution_provider,
        journal=dependencies.journal,
        account_loader=account_loader,
        market_clock=market_clock,
        config=config,
        logger=logger,
    )

    return TradingSteps(
        run_history=RunHistory(journal=dependencies.journal, market_clock=market_clock, config=config, logger=logger),
        account_loader=account_loader,
        account_risk_check=AccountRiskCheck(dependencies.journal, market_clock, config, logger),
        watch_stocks=WatchStocks(dependencies.watchlist_repository, market_clock, config, logger),
        signals=Signals(dependencies.journal, market_clock, config, logger),
        manual_signal=ManualSignal(dependencies.journal, market_clock, config, logger),
        decision_memory=DecisionMemory(knowledge_repository=dependencies.knowledge_repository, logger=logger),
        order_execution=order_execution,
        reporting=Reporting(dependencies.notification_provider, config, logger),
    )


def build_chat_steps(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> ChatSteps:
    chat_styler = ChatStylerService(config.sources.line.sentence_endings)

    return ChatSteps(
        context_loader=ContextLoader(
            repository=dependencies.conversation_repository, market_clock=market_clock, config=config, logger=logger
        ),
        ai_processor=AiProcessor(ai_provider=dependencies.ai_provider, chat_styler_provider=chat_styler, logger=logger),
        state_manager=StateManager(repository=dependencies.conversation_repository, market_clock=market_clock, logger=logger),
        dispatcher=Dispatcher(platform_provider=dependencies.platform_provider, logger=logger),
        reset_commands=frozenset(config.db.reset_commands),
        market_clock=market_clock,
    )


def build_valuation_steps(
    config: AppConfig,
    logger: ILoggingProvider,
    market_clock: TaiwanMarketClock,
    dependencies: ProviderDependencies,
    collect: CollectSteps,
    process: ProcessSteps,
) -> ValuationSteps:
    """Menus 5 and 6. It takes no TradingSteps: valuation never reaches orders, signals or the watchlist."""
    return ValuationSteps(
        stock_provider=dependencies.stock_provider,
        fundamentals_feed=FundamentalsFeed(dependencies.fundamentals_provider, market_clock, logger),
        data_collector=collect.data_collector,
        technical_filter=process.technical_filter,
        news_feed=collect.news_feed,
        valuation_explainer=ValuationExplainer(dependencies.ai_provider, market_clock, config, logger),
        technical_settings_repository=dependencies.technical_settings_repository,
        market_clock=market_clock,
        scenario_spread=config.valuation.scenario_spread,
    )


def build_account_history(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> AccountHistory:
    """Menu 7 and the account endpoint call it directly: one read-only operation, not a workflow."""
    return AccountHistory(
        execution_provider=dependencies.execution_provider,
        journal=dependencies.journal,
        stock_provider=dependencies.stock_provider,
        ohlcv_provider=dependencies.price_provider,
        market_clock=market_clock,
        config=config,
        logger=logger,
    )


def compose_runtime(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> Runtime:
    collect = build_collect_steps(config, logger, market_clock, dependencies)
    process = build_process_steps(config, logger, market_clock, dependencies)
    trading = build_trading_steps(config, logger, market_clock, dependencies)

    pipeline = Pipeline(
        collect=collect,
        process=process,
        trading=trading,
        chat=build_chat_steps(config, logger, market_clock, dependencies),
        valuation=build_valuation_steps(config, logger, market_clock, dependencies, collect, process),
        technical_settings_repository=dependencies.technical_settings_repository,
        logger=logger,
    )

    return Runtime(
        pipeline=pipeline,
        watch_stocks=trading.watch_stocks,
        account_history=build_account_history(config, logger, market_clock, dependencies),
        stock_provider=dependencies.stock_provider,
        journal=dependencies.journal,
        watchlist_repository=dependencies.watchlist_repository,
        technical_settings_repository=dependencies.technical_settings_repository,
        config=config,
        logger=logger,
    )


def create_line_webhook_handler(runtime: Runtime) -> LineWebhookHandler:
    """Built per request: the signature check refuses to build without LINE_CHANNEL_SECRET, and only the webhook needs it."""
    security_service = LineSecurityService(channel_secret=runtime.config.line.channel_secret, logger=runtime.logger)

    return LineWebhookHandler(security_service=security_service, pipeline=runtime.pipeline)


@asynccontextmanager
async def open_runtime() -> AsyncIterator[Runtime]:
    """
    Builds the runtime from config/ and the real adapters, once per process, and closes the database when the caller is done.
    It raises TradingSetupError for an unsafe trading setup and OutdatedDatabaseError for an old database, before any workflow runs.
    """
    config = load_settings()
    validate_trading_environment(config)

    logger = LoggerService(level=config.behavior.log_level)
    market_clock = TaiwanMarketClock()
    db = DatabaseConnector(config=config, logger=logger)

    try:
        await db.init_db()
        dependencies = await build_provider_dependencies(config, db, logger, market_clock)
        yield compose_runtime(config, logger, market_clock, dependencies)

    finally:
        await db.close()
