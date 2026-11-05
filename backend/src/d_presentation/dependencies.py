from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from secrets import compare_digest
from typing import Annotated

import chromadb
from fastapi import Depends, HTTPException, Request, status as http_status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr

from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.ai.sentiment_classifier import ISentimentClassifier
from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.chat.platform_provider import IPlatformProvider
from a_domain.ports.market.fundamentals_provider import IFundamentalsProvider
from a_domain.ports.market.news_source import INewsSource
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.notification_provider import INotificationProvider
from a_domain.ports.system.settings_files import ISettingsFiles
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import AiProvider, ExecutionProvider, SettingsFile
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import TradingSetupError, load_settings, validate_trading_environment
from b_application.pipeline import Pipeline
from b_application.use_cases.admin.settings_editor import SettingsEditor
from b_application.use_cases.admin.settings_save import SettingsSave
from b_application.use_cases.chat.chat_reply import ChatReply
from b_application.use_cases.chat.dispatcher import Dispatcher
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.fundamentals_feed import FundamentalsFeed
from b_application.use_cases.collect.index_history_loader import IndexHistoryLoader
from b_application.use_cases.collect.intraday_candidates import IntradayCandidates
from b_application.use_cases.collect.market_breadth_loader import MarketBreadthLoader
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.collect.market_scanner import MarketScanner
from b_application.use_cases.collect.most_traded import MostTraded
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.collect.official_change_feed import OfficialChangeFeed
from b_application.use_cases.collect.realtime_quote_feed import RealtimeQuoteFeed
from b_application.use_cases.collect.stock_lookup import StockLookup
from b_application.use_cases.collect.stock_search import StockSearch
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.indicator_readings import IndicatorReadings
from b_application.use_cases.process.sentiment_analyser import SentimentAnalyser
from b_application.use_cases.process.strategy_loader import StrategyLoader
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.process.technical_settings_editor import TechnicalSettingsEditor
from b_application.use_cases.ship.decision_memory import DecisionMemory
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.run_history import RunHistory
from b_application.use_cases.ship.run_reports import RunReports
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_history import AccountHistory
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.manual_signal import ManualSignal
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.use_cases.trade.order_outcome import OrderOutcome
from b_application.use_cases.trade.order_preparation import OrderPreparation
from b_application.use_cases.trade.unwatch_stocks import UnwatchStocks
from b_application.use_cases.trade.watch_stocks import WatchStocks
from b_application.use_cases.valuation.market_valuation_loader import MarketValuationLoader
from b_application.use_cases.valuation.valuation_appraiser import ValuationAppraiser
from b_application.use_cases.valuation.valuation_explainer import ValuationExplainer
from b_application.use_cases.valuation.valuation_screener import ValuationScreener
from c_infrastructure.ai_models.ai_adapter.claude_adapter import ClaudeAdapter
from c_infrastructure.ai_models.ai_adapter.gemini_adapter import GeminiAIAdapter
from c_infrastructure.ai_models.ai_adapter.grok_adapter import GrokAdapter
from c_infrastructure.ai_models.ai_adapter.openai_adapter import OpenAIAdapter
from c_infrastructure.ai_models.ai_adapter.web_search_adapter import WebSearchAiAdapter
from c_infrastructure.ai_models.sentiment_classifier import AiSentimentClassifier
from c_infrastructure.database.chroma.conversation_repository import ChromaConversationRepository
from c_infrastructure.database.chroma.knowledge_repository import ChromaKnowledgeRepository
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.sentiment_repository import SentimentRepository
from c_infrastructure.database.repositories.trading_journal import TradingJournal
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.feed.news.cnyes_news_provider import CnyesNewsProvider
from c_infrastructure.feed.news.yahoo_tw_news_provider import YahooTwNewsProvider
from c_infrastructure.feed.news_provider import NewsProvider
from c_infrastructure.feed.ptt_provider import PttProvider
from c_infrastructure.feed.tavily_provider import TavilySearchAdapter
from c_infrastructure.market.cached_price_provider import CachedPriceProvider
from c_infrastructure.market.mis_quote_provider import MisQuoteProvider
from c_infrastructure.market.mops_fundamentals_provider import MopsFundamentalsProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider
from c_infrastructure.platforms.line.line_adapter import LinePlatformAdapter
from c_infrastructure.platforms.line.line_notification_adapter import LineNotificationAdapter
from c_infrastructure.system.chat_styler_service import ChatStylerService
from c_infrastructure.system.logger_service import LoggerService
from c_infrastructure.system.market_clock import TaiwanMarketClock
from c_infrastructure.system.settings_files import SettingsFiles
from c_infrastructure.technical.sql_technical_settings_repository import SqlTechnicalSettingsRepository
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider
from d_presentation.web.market_valuation_cache import MarketValuationCache
from d_presentation.web.workflow_runs import WorkflowRuns


@dataclass(slots=True)
class Runtime:
    """
    The one object graph the CLI and the Web API run on. open_runtime() builds it from the real adapters;
    compose_runtime() wires the same graph over any ports, so tests and the order-gate check run it over fakes.
    """

    pipeline: Pipeline
    stock_provider: IStockProvider
    journal: ITradingJournal
    watchlist_repository: IWatchlistRepository
    settings_files: ISettingsFiles
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
    knowledge_repository: IKnowledgeRepository
    conversation_repository: IConversationRepository
    journal: ITradingJournal
    watchlist_repository: WatchlistRepository
    technical_settings_repository: ITechnicalSettingsRepository
    execution_provider: IExecutionProvider
    notification_provider: INotificationProvider | None
    platform_provider: IPlatformProvider | None
    settings_files: ISettingsFiles


def create_ai_provider(config: AppConfig, logger: ILoggingProvider) -> IAiProvider:
    provider = config.ai.active_model
    model_name = config.ai.available_models.get(provider)

    if model_name is None:
        raise ValueError(f"No model id resolved for provider {provider!s}. Add one under ai.available_models.")

    logger.debug(f"Creating AI adapter for provider: {provider.value} with model: {model_name}")

    match provider:
        case AiProvider.OPENAI:
            return OpenAIAdapter(config, logger, model_name, provider, config.ai.openai_api_key)
        case AiProvider.NVIDIA:
            return OpenAIAdapter(config, logger, model_name, provider, config.ai.nvidia_api_key, config.sources.ai.nvidia_base_url)
        case AiProvider.CLAUDE:
            return ClaudeAdapter(config=config, logger=logger, model_name=model_name)
        case AiProvider.GROK:
            return GrokAdapter(config=config, logger=logger, model_name=model_name)
        case AiProvider.GEMINI:
            return GeminiAIAdapter(config=config, logger=logger, model_name=model_name)
        case AiProvider.GROQ:
            return create_groq_provider(config, logger, model_name)


def create_groq_provider(config: AppConfig, logger: ILoggingProvider, model_name: str) -> IAiProvider:
    """Groq, searching the web first when web search is on and TAVILY_API_KEY and the RAG injection prompt are set."""
    groq = OpenAIAdapter(config, logger, model_name, AiProvider.GROQ, config.ai.groq_api_key, config.sources.ai.groq_base_url)
    results_prompt = config.ai.rag_injection_prompt

    if not (config.behavior.enable_web_search and config.tavily.api_key and results_prompt):
        return groq

    return WebSearchAiAdapter(
        ai_provider=groq,
        web_search_provider=TavilySearchAdapter(config=config, logger=logger),
        triggers=config.behavior.web_search_triggers,
        max_results=config.behavior.web_search_max_results,
        results_prompt=results_prompt,
        logger=logger,
    )


async def create_execution_provider(config: AppConfig, db: DatabaseConnector, logger: ILoggingProvider) -> IExecutionProvider:
    if config.trading.execution_provider == ExecutionProvider.MOCK:
        return MockExecutionProvider(db=db, config=config, logger=logger)

    # Imported only for Shioaji: importing shioaji creates shioaji.log in the working directory and logs a warning.
    from shioaji import Shioaji

    from c_infrastructure.trading.shioaji.execution_provider import ShioajiExecutionProvider

    broker = "simulation" if config.shioaji.simulation else "production"

    try:
        provider = ShioajiExecutionProvider(client=Shioaji(simulation=config.shioaji.simulation), config=config, logger=logger)
        await provider.connect()

    except Exception as error:
        raise TradingSetupError(f"Shioaji {broker} login failed: {type(error).__name__}: {error}") from error

    logger.info(f"Logged in to Shioaji {broker}. Order mode: {config.trading.order_mode.value}")

    return provider


def create_news_sources(config: AppConfig, logger: ILoggingProvider) -> tuple[INewsSource, ...]:
    """The news sites in the order they are asked: cnyes first, then Yahoo for what cnyes did not find."""
    return (CnyesNewsProvider(config.sources.news, logger), YahooTwNewsProvider(config.sources.news, logger))


def create_platform_provider(config: AppConfig, logger: ILoggingProvider) -> IPlatformProvider | None:
    """The LINE chat platform, or None while LINE_CHANNEL_ACCESS_TOKEN is unset: the adapter refuses to build without it."""
    if not config.line.channel_access_token:
        return None

    return LinePlatformAdapter(config=config, logger=logger)


def create_notification_provider(config: AppConfig, logger: ILoggingProvider) -> INotificationProvider | None:
    if not config.notifications.enabled:
        return None

    return LineNotificationAdapter(config=config, logger=logger)


def create_price_provider(
    config: AppConfig, db: DatabaseConnector, logger: ILoggingProvider, market_clock: TaiwanMarketClock
) -> CachedPriceProvider:
    """Yahoo daily history cached in the database, and TWSE MIS realtime quotes."""
    return CachedPriceProvider(
        history_provider=YahooFinanceProvider(
            market_clock=market_clock, market_data=config.market_data, yahoo=config.sources.yahoo, logger=logger
        ),
        quote_provider=MisQuoteProvider(exchange=config.sources.exchange, market_data=config.market_data, logger=logger),
        db=db,
        market_data=config.market_data,
        logger=logger,
        market_clock=market_clock,
    )


async def build_provider_dependencies(
    config: AppConfig, db: DatabaseConnector, logger: ILoggingProvider, market_clock: TaiwanMarketClock
) -> ProviderDependencies:
    stock_provider = TaiwanStockProvider(
        exchange=config.sources.exchange, market_clock=market_clock, market_data=config.market_data, logger=logger
    )

    logger.info(f"Opening ChromaDB at: {config.db.chroma_persist_path}")
    chroma_client = chromadb.PersistentClient(path=config.db.chroma_persist_path)

    ai_provider = create_ai_provider(config, logger)

    return ProviderDependencies(
        stock_provider=stock_provider,
        price_provider=create_price_provider(config, db, logger, market_clock),
        fundamentals_provider=MopsFundamentalsProvider(db=db, market_clock=market_clock, mops=config.sources.mops, logger=logger),
        news_provider=NewsProvider(create_news_sources(config, logger), config, logger),
        social_media_provider=PttProvider(config=config, logger=logger, stock_provider=stock_provider),
        ai_provider=ai_provider,
        sentiment_classifier=AiSentimentClassifier(ai_provider, SentimentRepository(db), config, logger),
        knowledge_repository=ChromaKnowledgeRepository(chroma_client, logger),
        conversation_repository=ChromaConversationRepository(chroma_client, logger),
        journal=TradingJournal(db=db),
        watchlist_repository=WatchlistRepository(db=db, logger=logger, market_clock=market_clock),
        technical_settings_repository=SqlTechnicalSettingsRepository(db),
        execution_provider=await create_execution_provider(config, db, logger),
        notification_provider=create_notification_provider(config, logger),
        platform_provider=create_platform_provider(config, logger),
        settings_files=SettingsFiles(
            project_root=config.project_root,
            max_bytes=config.api.settings_file_max_bytes,
            backups_kept=config.api.settings_backups_kept,
            logger=logger,
        ),
    )


def build_pipeline(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> Pipeline:
    """Every use case once, over the given ports. The trading and the valuation operations share the collect and process steps."""
    stocks, prices = dependencies.stock_provider, dependencies.price_provider
    journal, broker = dependencies.journal, dependencies.execution_provider
    chat_styler = ChatStylerService(config.sources.line.sentence_endings, config.sources.line.max_message_length)

    return Pipeline(
        strategy_loader=StrategyLoader(dependencies.technical_settings_repository, config, logger),
        technical_settings_editor=TechnicalSettingsEditor(dependencies.technical_settings_repository, config),
        run_history=RunHistory(journal, market_clock, config, logger),
        account_loader=AccountLoader(broker, stocks, logger),
        market_scanner=MarketScanner(stocks, logger),
        stock_lookup=StockLookup(stocks, logger),
        stock_search=StockSearch(stocks, config),
        most_traded=MostTraded(stocks, config),
        market_breadth_loader=MarketBreadthLoader(stocks, dependencies.fundamentals_provider),
        index_history_loader=IndexHistoryLoader(prices, market_clock, config),
        buzz_scanner=BuzzScanner(dependencies.social_media_provider, stocks, logger, config),
        intraday_candidates=IntradayCandidates(stocks, dependencies.watchlist_repository, logger),
        data_collector=MarketDataCollector(prices, market_clock, config, logger),
        official_change_feed=OfficialChangeFeed(stocks),
        realtime_quote_feed=RealtimeQuoteFeed(prices, market_clock, config, logger),
        technical_filter=TechnicalFilter(logger),
        indicator_readings=IndicatorReadings(),
        news_feed=NewsFeed(dependencies.news_provider, config, logger),
        ai_analyser=AiAnalyser(dependencies.ai_provider, dependencies.knowledge_repository, market_clock, config, logger),
        sentiment_analyser=SentimentAnalyser(dependencies.sentiment_classifier, config, logger),
        watch_stocks=WatchStocks(dependencies.watchlist_repository, market_clock, config, logger),
        unwatch_stocks=UnwatchStocks(dependencies.watchlist_repository, logger),
        account_risk_check=AccountRiskCheck(journal, market_clock, config, logger),
        signals=Signals(journal, market_clock, config, logger),
        manual_signal=ManualSignal(journal, market_clock, config, logger),
        decision_memory=DecisionMemory(dependencies.knowledge_repository, logger),
        order_preparation=OrderPreparation(journal, market_clock, config, logger),
        order_execution=OrderExecution(broker, journal, market_clock, logger),
        order_outcome=OrderOutcome(broker, journal, market_clock, logger),
        reporting=Reporting(dependencies.notification_provider, config, logger),
        run_reports=RunReports(journal, logger),
        account_history=AccountHistory(broker, journal, stocks, prices, market_clock, config, logger),
        fundamentals_feed=FundamentalsFeed(dependencies.fundamentals_provider, market_clock, logger),
        market_valuation_loader=MarketValuationLoader(stocks, market_clock, config),
        valuation_appraiser=ValuationAppraiser(config),
        valuation_screener=ValuationScreener(config),
        valuation_explainer=ValuationExplainer(dependencies.ai_provider, market_clock, config, logger),
        chat_reply=ChatReply(
            dependencies.ai_provider, chat_styler, dependencies.conversation_repository, market_clock, config, logger
        ),
        dispatcher=Dispatcher(dependencies.platform_provider, logger),
        settings_editor=SettingsEditor(dependencies.settings_files),
        settings_save=SettingsSave(dependencies.settings_files, market_clock, logger),
    )


def compose_runtime(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> Runtime:
    return Runtime(
        pipeline=build_pipeline(config, logger, market_clock, dependencies),
        stock_provider=dependencies.stock_provider,
        journal=dependencies.journal,
        watchlist_repository=dependencies.watchlist_repository,
        settings_files=dependencies.settings_files,
        config=config,
        logger=logger,
    )


@asynccontextmanager
async def open_runtime() -> AsyncGenerator[Runtime]:
    """
    Builds the runtime from config/ and the real adapters, once per process, and closes the database when the caller is done.
    It raises InvalidSettingsError for settings that do not validate, TradingSetupError for an unsafe trading setup and
    OutdatedDatabaseError for an old database, before any workflow runs.
    """
    config = load_settings()
    validate_trading_environment(config)

    logger = LoggerService(level=config.behavior.log_level)
    market_clock = TaiwanMarketClock(config.market_hours)
    db = DatabaseConnector(config=config, logger=logger)

    try:
        await db.init_db()
        dependencies = await build_provider_dependencies(config, db, logger, market_clock)
        yield compose_runtime(config, logger, market_clock, dependencies)

    finally:
        await db.close()


def create_workflow_runs(runtime: Runtime) -> WorkflowRuns:
    """The Web API's background runs. The app's lifespan creates one per server, next to the runtime it opened."""
    return WorkflowRuns(runtime.logger)


def create_market_valuation_cache(runtime: Runtime) -> MarketValuationCache:
    return MarketValuationCache(runtime.pipeline.load_market_valuation, ttl_seconds=runtime.config.api.valuation_cache_minutes * 60)


bearer = HTTPBearer(auto_error=False, description="API_TOKEN for the owner's endpoints, ADMIN_API_TOKEN for /v1/admin.")


def get_runtime(request: Request) -> Runtime:
    """The runtime the app's lifespan built once at startup."""
    return request.app.state.runtime


def get_workflow_runs(request: Request) -> WorkflowRuns:
    return request.app.state.workflow_runs


def get_market_valuation_cache(request: Request) -> MarketValuationCache:
    return request.app.state.market_valuation_cache


RuntimeDependency = Annotated[Runtime, Depends(get_runtime)]
WorkflowRunsDependency = Annotated[WorkflowRuns, Depends(get_workflow_runs)]
MarketValuationDependency = Annotated[MarketValuationCache, Depends(get_market_valuation_cache)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def require_known_host(request: Request, runtime: RuntimeDependency) -> None:
    """
    Every /v1 request: 400 unless its Host header names one of api.allowed_hosts, so a page on another site cannot
    reach the API through DNS rebinding.
    """
    if request.url.hostname not in runtime.config.api.allowed_hosts:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, "Unknown host.")


def check_bearer(expected: SecretStr, credentials: HTTPAuthorizationCredentials | None) -> None:
    if credentials is None or not compare_digest(credentials.credentials.encode(), expected.get_secret_value().encode()):
        raise HTTPException(
            http_status.HTTP_401_UNAUTHORIZED, "A valid bearer token is required.", headers={"WWW-Authenticate": "Bearer"}
        )


def require_api_token(runtime: RuntimeDependency, credentials: Credentials) -> None:
    """
    Every write and every read of the owner's private data: 403 while API_TOKEN is unset, 401 without its bearer
    token. A write's body `confirm: true` is checked after.
    """
    token = runtime.config.api.token

    if token is None:
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, "Private endpoints are disabled. Set API_TOKEN to enable them.")

    check_bearer(token, credentials)


def require_admin_token(runtime: RuntimeDependency, credentials: Credentials) -> None:
    """The settings-file endpoints: 403 while ADMIN_API_TOKEN is unset or equals API_TOKEN, 401 without its bearer token."""
    api = runtime.config.api

    if api.admin_token is None or not api.admin_enabled:
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN, "Administration is disabled. Set ADMIN_API_TOKEN, different from API_TOKEN."
        )

    check_bearer(api.admin_token, credentials)


def require_mock_broker(runtime: RuntimeDependency) -> None:
    """
    Buzz and Intraday send orders. The Web API starts them only on the mock broker, so a browser never reaches a
    real account: 403 for any other execution provider, whatever the order mode.
    """
    if runtime.config.trading.execution_provider != ExecutionProvider.MOCK:
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            "The Web API starts Buzz and Intraday only on the mock broker. Use the CLI for another execution provider.",
        )


KnownHost = Depends(require_known_host)


def running_settings_revision(runtime: Runtime, file: SettingsFile) -> str | None:
    """The revision of the file this process loaded at startup, the settings it runs on."""
    return runtime.config.settings_revisions.get(file)


ApiToken = Depends(require_api_token)
AdminToken = Depends(require_admin_token)
MockBroker = Depends(require_mock_broker)
