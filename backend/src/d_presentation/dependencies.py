from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from secrets import compare_digest
from typing import Annotated, Any

import chromadb
import yaml
from fastapi import Depends, HTTPException, Request, status as http_status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import AiProvider, ExecutionProvider, OrderMode, SystemEnvironment
from b_application.config.app_config import AppConfig
from b_application.pipeline import ChatSteps, CollectSteps, Pipeline, ProcessSteps, TradingSteps, ValuationSteps
from b_application.use_cases.chat.ai_processor import AiProcessor
from b_application.use_cases.chat.context_loader import ContextLoader
from b_application.use_cases.chat.dispatcher import Dispatcher
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.fundamentals_feed import FundamentalsFeed
from b_application.use_cases.collect.intraday_candidates import IntradayCandidates
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.collect.market_scanner import MarketScanner
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.collect.realtime_quote_feed import RealtimeQuoteFeed
from b_application.use_cases.collect.stock_lookup import StockLookup
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
from b_application.use_cases.trade.order_outcome import OrderOutcome
from b_application.use_cases.trade.order_preparation import OrderPreparation
from b_application.use_cases.trade.watch_stocks import WatchStocks
from c_infrastructure.ai_models.ai_adapter.gemini_adapter import GeminiAIAdapter
from c_infrastructure.ai_models.ai_adapter.grok_adapter import GrokAdapter
from c_infrastructure.ai_models.ai_adapter.groq_adapter import GroqAIAdapter
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
from c_infrastructure.technical.yaml_technical_settings_repository import YamlTechnicalSettingsRepository
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider
from d_presentation.web.workflow_runs import WorkflowRuns


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
    knowledge_repository: IKnowledgeRepository
    conversation_repository: IConversationRepository
    journal: ITradingJournal
    watchlist_repository: WatchlistRepository
    technical_settings_repository: ITechnicalSettingsRepository
    execution_provider: IExecutionProvider
    notification_provider: INotificationProvider | None
    platform_provider: IPlatformProvider | None


def get_project_root() -> Path:
    """The nearest folder above this file that holds the justfile or .git: config/, .env and stock_agent.db live there."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "justfile").exists() or (parent / ".git").exists():
            return parent

    raise FileNotFoundError("Could not find project root.")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    with path.open(encoding="utf-8") as config_file:
        return yaml.safe_load(config_file) or {}


def inject_prompt_settings(settings: dict[str, Any], instructions: dict[str, Any]) -> None:
    """Copies the AI prompts of config/instructions.yaml into the ai and prompts sections of the settings."""
    if not instructions:
        return

    ai_settings = settings.setdefault("ai", {})
    ai_settings["system_prompt"] = instructions.get("system_prompt")
    ai_settings["rag_injection_prompt"] = instructions.get("rag_injection_prompt")

    prompts = settings.setdefault("prompts", {})
    prompts["analysis_report_fundamental"] = instructions.get("ai_analysis_report_prompt_fundamental")
    prompts["analysis_report_momentum"] = instructions.get("ai_analysis_report_prompt_momentum")
    prompts["valuation_explanation"] = instructions.get("ai_valuation_explanation_prompt")
    prompts["social_sentiment"] = instructions.get("social_sentiment_prompt")


def load_settings() -> AppConfig:
    """config/appsetting.yaml with the prompts of config/instructions.yaml. AppConfig reads the secrets from .env."""
    project_root = get_project_root()
    settings = load_yaml(project_root / "config" / "appsetting.yaml")

    inject_prompt_settings(settings, load_yaml(project_root / "config" / "instructions.yaml"))

    return AppConfig(project_root=project_root, **settings)


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
    provider = config.ai.active_model
    model_name = config.ai.available_models.get(provider)

    if model_name is None:
        raise ValueError(f"No model id resolved for provider {provider!s}. Add one under ai.available_models.")

    logger.debug(f"Creating AI adapter for provider: {provider.value} with model: {model_name}")

    match provider:
        case AiProvider.OPENAI:
            return OpenAIAdapter(config=config, logger=logger, model_name=model_name)
        case AiProvider.GROK:
            return GrokAdapter(config=config, logger=logger, model_name=model_name)
        case AiProvider.GEMINI:
            return GeminiAIAdapter(config=config, logger=logger, model_name=model_name)
        case AiProvider.GROQ:
            return create_groq_provider(config, logger, model_name)


def create_groq_provider(config: AppConfig, logger: ILoggingProvider, model_name: str) -> IAiProvider:
    """Groq, searching the web first when web search is on and TAVILY_API_KEY and the RAG injection prompt are set."""
    groq = GroqAIAdapter(config=config, logger=logger, model_name=model_name)
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
        history_provider=YahooFinanceProvider(market_clock=market_clock, market_data=config.market_data, logger=logger),
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

    technical_path = config.project_root / "config" / "technical.yaml"
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
        technical_settings_repository=YamlTechnicalSettingsRepository(technical_path),
        execution_provider=await create_execution_provider(config, db, logger),
        notification_provider=create_notification_provider(config, logger),
        platform_provider=create_platform_provider(config, logger),
    )


def build_collect_steps(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> CollectSteps:
    buzz_scanner = BuzzScanner(
        social_media_provider=dependencies.social_media_provider,
        stock_provider=dependencies.stock_provider,
        logger=logger,
        config=config,
    )

    news_feed = NewsFeed(news_provider=dependencies.news_provider, config=config, logger=logger)

    return CollectSteps(
        market_scanner=MarketScanner(stock_provider=dependencies.stock_provider, logger=logger),
        stock_lookup=StockLookup(stock_provider=dependencies.stock_provider, logger=logger),
        intraday_candidates=IntradayCandidates(
            stock_provider=dependencies.stock_provider, watchlist_repository=dependencies.watchlist_repository, logger=logger
        ),
        data_collector=MarketDataCollector(
            ohlcv_provider=dependencies.price_provider, market_clock=market_clock, config=config, logger=logger
        ),
        realtime_quote_feed=RealtimeQuoteFeed(
            quote_provider=dependencies.price_provider, market_clock=market_clock, config=config, logger=logger
        ),
        buzz_scanner=buzz_scanner,
        news_feed=news_feed,
    )


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
        sentiment_analyser=SentimentAnalyser(classifier=dependencies.sentiment_classifier, config=config, logger=logger),
    )


def build_trading_steps(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> TradingSteps:
    broker, journal = dependencies.execution_provider, dependencies.journal

    return TradingSteps(
        run_history=RunHistory(journal=journal, market_clock=market_clock, config=config, logger=logger),
        account_loader=AccountLoader(execution_provider=broker, stock_provider=dependencies.stock_provider, logger=logger),
        account_risk_check=AccountRiskCheck(dependencies.journal, market_clock, config, logger),
        watch_stocks=WatchStocks(dependencies.watchlist_repository, market_clock, config, logger),
        signals=Signals(dependencies.journal, market_clock, config, logger),
        manual_signal=ManualSignal(dependencies.journal, market_clock, config, logger),
        decision_memory=DecisionMemory(knowledge_repository=dependencies.knowledge_repository, logger=logger),
        order_preparation=OrderPreparation(journal=journal, market_clock=market_clock, config=config, logger=logger),
        order_execution=OrderExecution(execution_provider=broker, journal=journal, market_clock=market_clock, logger=logger),
        order_outcome=OrderOutcome(execution_provider=broker, journal=journal, market_clock=market_clock, logger=logger),
        reporting=Reporting(dependencies.notification_provider, config, logger),
    )


def build_chat_steps(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> ChatSteps:
    chat_styler = ChatStylerService(config.sources.line.sentence_endings, config.sources.line.max_message_length)

    return ChatSteps(
        context_loader=ContextLoader(
            repository=dependencies.conversation_repository, market_clock=market_clock, config=config, logger=logger
        ),
        ai_processor=AiProcessor(ai_provider=dependencies.ai_provider, chat_styler_provider=chat_styler, logger=logger),
        conversation_repository=dependencies.conversation_repository,
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
        close_max_missed_sessions=config.freshness.daily_close_max_missed_sessions,
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


@asynccontextmanager
async def open_runtime() -> AsyncIterator[Runtime]:
    """
    Builds the runtime from config/ and the real adapters, once per process, and closes the database when the caller is done.
    It raises TradingSetupError for an unsafe trading setup and OutdatedDatabaseError for an old database, before any workflow runs.
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


bearer = HTTPBearer(auto_error=False, description="The value of API_TOKEN. Reads need no token.")


def get_runtime(request: Request) -> Runtime:
    """The runtime the app's lifespan built once at startup."""
    return request.app.state.runtime


def get_workflow_runs(request: Request) -> WorkflowRuns:
    return request.app.state.workflow_runs


RuntimeDependency = Annotated[Runtime, Depends(get_runtime)]
WorkflowRunsDependency = Annotated[WorkflowRuns, Depends(get_workflow_runs)]


def require_write_permission(
    runtime: RuntimeDependency, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> None:
    """Every write: 403 while API_TOKEN is unset, 401 without its bearer token. The body's `confirm: true` is checked after."""
    token = runtime.config.api.token

    if token is None:
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, "Writes are disabled. Set API_TOKEN to enable them.")

    if credentials is None or not compare_digest(credentials.credentials.encode(), token.get_secret_value().encode()):
        raise HTTPException(
            http_status.HTTP_401_UNAUTHORIZED, "A valid bearer token is required.", headers={"WWW-Authenticate": "Bearer"}
        )


WritePermission = Depends(require_write_permission)
