import asyncio
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

import chromadb
from chromadb.api import ClientAPI
from pydantic import SecretStr

from a_domain.model.system.user import User
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.ai.sentiment_classifier import ISentimentClassifier
from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.chat.platform_provider import IPlatformProvider
from a_domain.ports.market.fundamentals_provider import IFundamentalsProvider
from a_domain.ports.market.news_source import INewsSource
from a_domain.ports.system.attempt_log import IAttemptLog
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.notification_provider import INotificationProvider
from a_domain.ports.system.settings_files import ISettingsFiles
from a_domain.ports.system.user_store import IUserStore
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import AiProvider, ExecutionProvider, Permission
from a_domain.types.errors import RealBrokerRefused
from a_domain.types.ids import UserId
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import (
    AccountsSetupError,
    InvalidSettingsError,
    TradingSetupError,
    get_project_root,
    load_settings,
)
from b_application.pipeline import Pipeline
from b_application.use_cases.admin.editor_access import EditorAccess
from b_application.use_cases.admin.settings_audit import SettingsAudit
from b_application.use_cases.admin.settings_backups import SettingsBackups
from b_application.use_cases.admin.settings_confirmation import SettingsConfirmation
from b_application.use_cases.admin.settings_editor import SettingsEditor
from b_application.use_cases.admin.settings_form_editor import SettingsFormEditor
from b_application.use_cases.admin.settings_reader import SettingsReader
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
from b_application.use_cases.ship.recent_runs import RecentRuns
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.run_history import RunHistory
from b_application.use_cases.ship.run_lookup import RunLookup
from b_application.use_cases.ship.run_reports import RunReports
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_history import AccountHistory
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.active_watchlist import ActiveWatchlist
from b_application.use_cases.trade.manual_signal import ManualSignal
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.use_cases.trade.order_outcome import OrderOutcome
from b_application.use_cases.trade.order_preparation import OrderPreparation
from b_application.use_cases.trade.unwatch_stocks import UnwatchStocks
from b_application.use_cases.trade.watch_stocks import WatchStocks
from b_application.use_cases.users.ai_model_choice import AiModelChoice
from b_application.use_cases.users.ai_model_lookup import AiModelLookup
from b_application.use_cases.users.first_administrator_setup import FirstAdministratorSetup
from b_application.use_cases.users.password_reset import PasswordReset
from b_application.use_cases.users.session_start import SessionStart
from b_application.use_cases.users.session_user import SessionUser
from b_application.use_cases.users.sign_in_attempt import SignInAttempt
from b_application.use_cases.users.sign_in_options import SignInOptions
from b_application.use_cases.users.sign_out import SignOut
from b_application.use_cases.users.user_change import UserChange
from b_application.use_cases.users.user_directory import UserDirectory
from b_application.use_cases.users.user_lookup import UserLookup
from b_application.use_cases.users.user_registration import UserRegistration
from b_application.use_cases.valuation.market_valuation_loader import MarketValuationLoader
from b_application.use_cases.valuation.valuation_appraiser import ValuationAppraiser
from b_application.use_cases.valuation.valuation_explainer import ValuationExplainer
from b_application.use_cases.valuation.valuation_screener import ValuationScreener
from c_infrastructure.ai_models.ai_adapter.claude_adapter import ClaudeAdapter
from c_infrastructure.ai_models.ai_adapter.daily_capped_ai_provider import DailyCappedAiProvider
from c_infrastructure.ai_models.ai_adapter.gemini_adapter import GeminiAIAdapter
from c_infrastructure.ai_models.ai_adapter.grok_adapter import GrokAdapter
from c_infrastructure.ai_models.ai_adapter.openai_adapter import OpenAIAdapter
from c_infrastructure.ai_models.ai_adapter.web_search_adapter import WebSearchAiAdapter
from c_infrastructure.ai_models.sentiment_classifier import AiSentimentClassifier
from c_infrastructure.database.chroma.conversation_repository import ChromaConversationRepository
from c_infrastructure.database.chroma.knowledge_repository import ChromaKnowledgeRepository
from c_infrastructure.database.chroma.schema import ChromaCollection
from c_infrastructure.database.db_connector import DatabaseConnector, OutdatedDatabaseError
from c_infrastructure.database.models.user_dto import LEGACY_OWNER_ID, load_accounts_key
from c_infrastructure.database.repositories.sentiment_repository import SentimentRepository
from c_infrastructure.database.repositories.trading_journal import TradingJournal
from c_infrastructure.database.repositories.user_store import AccountsKeyError, SqlUserStore
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
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from c_infrastructure.system.chat_styler_service import ChatStylerService
from c_infrastructure.system.logger_service import LoggerService
from c_infrastructure.system.market_clock import TaiwanMarketClock
from c_infrastructure.system.settings_files import SettingsFiles
from c_infrastructure.technical.sql_technical_settings_repository import SqlTechnicalSettingsRepository
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider
from d_presentation.web.market_valuation_cache import MarketValuationCache


@dataclass(frozen=True, slots=True)
class Runtime:
    """
    What the CLI and the Web API run on. pipeline_for(user) is that user's object graph, over the ports that hold that
    user's data, built per call, so nothing caches one and no role or status change waits on a cache. signed_out is the
    graph of nobody, built once, for sign-in, setup, the public market pages and LINE chat: its ports that hold users'
    data refuse their first call with SignInRequired. open_runtime() builds it from the real adapters;
    compose_runtime() wires the same graph over any ports, so tests and the order-gate check run it over fakes.
    """

    pipeline_for: Callable[[User], Pipeline]
    signed_out: Pipeline
    market_valuation_cache: MarketValuationCache
    """
    The market valuation this runtime loaded, reused for api.valuation_cache_minutes. It lives and dies with the
    runtime, so its loader and its lifetime always come from the settings the runtime runs on.
    """

    config: AppConfig
    logger: ILoggingProvider

    def become_current(self) -> None:
        """What the process takes from the settings of the runtime that serves new work: the log level of its one logger."""
        self.logger.set_level(self.config.behavior.log_level)


@dataclass(frozen=True, slots=True)
class ProcessState:
    """
    What one process keeps whichever settings it runs on, handed to every runtime it opens: the logger (loguru is
    process-wide; the current runtime sets its level), the recent sign-in attempts, so no settings change resets the
    attempt limits, and the write lock of the shared caches.
    """

    logger: ILoggingProvider
    attempt_log: IAttemptLog
    cache_writes: asyncio.Lock
    """
    One save at a time of the price history, the MOPS EPS pages and the classified posts, across every runtime: a
    retired runtime still finishing a run and the current one would otherwise insert the same row at once.
    """


@dataclass(slots=True)
class OwnedPorts:
    """
    The adapters that hold one user's data, all built for the same user by ProviderDependencies.owned_ports. Built for
    None (signed out), each refuses its first call with SignInRequired.
    """

    journal: ITradingJournal
    watchlist_repository: IWatchlistRepository
    technical_settings_repository: ITechnicalSettingsRepository
    knowledge_repository: IKnowledgeRepository
    mock_broker: IExecutionProvider
    ai_provider: IAiProvider
    """
    The user's counted provider, on the AI model the user chose while the site offers it, else on ai.active_model,
    capped at accounts.daily_ai_calls unless the user has UNCAPPED_AI. Every paid call of a workflow or an explanation
    goes through it.
    """
    sentiment_classifier: ISentimentClassifier


@dataclass(slots=True)
class ProviderDependencies:
    """The adapters shared by every owner, built once per process, and the factory of one owner's adapters."""

    stock_provider: TaiwanStockProvider
    price_provider: CachedPriceProvider
    fundamentals_provider: IFundamentalsProvider
    news_provider: NewsProvider
    social_media_provider: PttProvider
    ai_provider: IAiProvider
    """The installation's own provider, on ai.active_model, uncounted. Only LINE chat uses it; LINE chat stays as it is."""
    conversation_repository: IConversationRepository
    notification_provider: INotificationProvider | None
    platform_provider: IPlatformProvider | None
    settings_files: ISettingsFiles
    user_store: IUserStore
    attempt_log: IAttemptLog
    real_broker: IExecutionProvider | None
    """Shioaji, logged in at startup when trading.execution_provider is shioaji; None on the mock broker."""
    owned_ports: Callable[[User | None], OwnedPorts]
    """A user, or None signed out -> the adapters that hold that user's data. The order-gate check passes fakes."""


def create_ai_provider(config: AppConfig, logger: ILoggingProvider, provider: AiProvider) -> IAiProvider:
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


@asynccontextmanager
async def open_real_broker(config: AppConfig, logger: ILoggingProvider) -> AsyncGenerator[IExecutionProvider | None]:
    """
    The logged-in Shioaji provider, which only administrators' pipelines hold, or None on the mock broker. It logs out
    when the caller is done, and when the login or a check after it fails, times out or is cancelled.
    """
    if config.trading.execution_provider == ExecutionProvider.MOCK:
        yield None
        return

    # Imported only for Shioaji: importing shioaji creates shioaji.log in the working directory and logs a warning.
    from shioaji import Shioaji

    from c_infrastructure.trading.shioaji.execution_provider import ShioajiExecutionProvider

    login = config.shioaji.login(config.environment)
    broker = "simulation" if login.simulation else "production"
    provider = ShioajiExecutionProvider(client=Shioaji(simulation=login.simulation), login=login, config=config, logger=logger)

    try:
        try:
            await provider.connect()
        except Exception as error:
            raise TradingSetupError(f"Shioaji {broker} login failed: {type(error).__name__}: {error}") from error

        logger.info(f"Logged in to Shioaji {broker}. Order mode: {config.trading.order_mode.value}")
        yield provider

    finally:
        await provider.close()


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
    config: AppConfig, db: DatabaseConnector, process: ProcessState, market_clock: TaiwanMarketClock
) -> CachedPriceProvider:
    """Yahoo daily history cached in the database, and TWSE MIS realtime quotes."""
    logger = process.logger
    return CachedPriceProvider(
        history_provider=YahooFinanceProvider(
            market_clock=market_clock, market_data=config.market_data, yahoo=config.sources.yahoo, logger=logger
        ),
        quote_provider=MisQuoteProvider(exchange=config.sources.exchange, market_data=config.market_data, logger=logger),
        db=db,
        market_data=config.market_data,
        logger=logger,
        market_clock=market_clock,
        write_lock=process.cache_writes,
    )


async def build_provider_dependencies(
    config: AppConfig,
    db: DatabaseConnector,
    process: ProcessState,
    market_clock: TaiwanMarketClock,
    accounts_key: SecretStr,
    real_broker: IExecutionProvider | None,
) -> ProviderDependencies:
    logger = process.logger
    stock_provider = TaiwanStockProvider(
        exchange=config.sources.exchange, market_clock=market_clock, market_data=config.market_data, logger=logger
    )

    logger.info(f"Opening ChromaDB at: {config.db.chroma_persist_path}")
    chroma_client = chromadb.PersistentClient(path=config.db.chroma_persist_path)

    ai_providers = {provider: create_ai_provider(config, logger, provider) for provider in config.ai.offered_models}

    return ProviderDependencies(
        stock_provider=stock_provider,
        price_provider=create_price_provider(config, db, process, market_clock),
        fundamentals_provider=MopsFundamentalsProvider(
            db=db, market_clock=market_clock, mops=config.sources.mops, logger=logger, write_lock=process.cache_writes
        ),
        news_provider=NewsProvider(create_news_sources(config, logger), config, logger),
        social_media_provider=PttProvider(config=config, logger=logger, stock_provider=stock_provider),
        ai_provider=ai_providers[config.ai.active_model],
        conversation_repository=ChromaConversationRepository(chroma_client, logger),
        notification_provider=create_notification_provider(config, logger),
        platform_provider=create_platform_provider(config, logger),
        settings_files=SettingsFiles(
            project_root=config.project_root,
            max_bytes=config.api.settings_file_max_bytes,
            backups_kept=config.api.settings_backups_kept,
            logger=logger,
        ),
        user_store=SqlUserStore(db, accounts_key, logger),
        attempt_log=process.attempt_log,
        real_broker=real_broker,
        owned_ports=create_owned_ports(config, db, chroma_client, ai_providers, market_clock, logger, process.cache_writes),
    )


def create_owned_ports(
    config: AppConfig,
    db: DatabaseConnector,
    chroma_client: ClientAPI,
    ai_providers: Mapping[AiProvider, IAiProvider],
    market_clock: TaiwanMarketClock,
    logger: ILoggingProvider,
    cache_writes: asyncio.Lock,
) -> Callable[[User | None], OwnedPorts]:
    """
    The real factory of one user's adapters: one connector bound to the user, over the one database and Chroma client,
    and the provider of the AI model config.ai.model_for picks for the user from `ai_providers`, one per offered model.
    `cache_writes` is the process's write lock of the shared caches.
    """
    sentiment_repository = SentimentRepository(db, cache_writes)

    def owned_ports(user: User | None) -> OwnedPorts:
        owner_id = user.user_id if user is not None else None
        daily_ai_calls = None if user is not None and Permission.UNCAPPED_AI in user.permissions else config.accounts.daily_ai_calls
        owners_db = db.for_owner(owner_id)
        ai_provider = ai_providers[config.ai.model_for(user.ai_model if user is not None else None)]
        counted = DailyCappedAiProvider(ai_provider, owners_db, market_clock, daily_ai_calls, config.accounts.daily_ai_calls_total)
        return OwnedPorts(
            journal=TradingJournal(owners_db),
            watchlist_repository=WatchlistRepository(owners_db, logger, market_clock),
            technical_settings_repository=SqlTechnicalSettingsRepository(owners_db),
            knowledge_repository=ChromaKnowledgeRepository(chroma_client, knowledge_collection(owner_id), logger),
            mock_broker=MockExecutionProvider(owners_db, config, logger),
            ai_provider=counted,
            sentiment_classifier=AiSentimentClassifier(counted, sentiment_repository, config, logger),
        )

    return owned_ports


def knowledge_collection(owner_id: UserId | None) -> str | None:
    """
    The owner's Chroma collection of decisions. The legacy owner keeps market_knowledge, which the single-owner versions
    wrote, so its decision memory needs no copy; every other owner's is market_knowledge-<owner id>. None signed out.
    """
    if owner_id is None:
        return None

    if owner_id == LEGACY_OWNER_ID:
        return ChromaCollection.MARKET_KNOWLEDGE

    return f"{ChromaCollection.MARKET_KNOWLEDGE}-{owner_id}"


def broker_for(dependencies: ProviderDependencies, owned: OwnedPorts, user: User | None) -> IExecutionProvider:
    """
    The user's own mock broker, or the installation's real broker for a user with USE_REAL_BROKER. The Web refuses
    every other user on a real-broker installation before any Pipeline is built (session.py), and this refuses them
    again, so no Pipeline of theirs ever exists. A signed-out pipeline never holds the real broker: its mock broker
    refuses every call, so a public route cannot read the real account.
    """
    if dependencies.real_broker is None or user is None:
        return owned.mock_broker

    if Permission.USE_REAL_BROKER not in user.permissions:
        raise RealBrokerRefused("This installation trades on a real broker. Only an administrator may use its private pages.")

    return dependencies.real_broker


def build_pipeline(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies, user: User | None
) -> Pipeline:
    """
    Every use case once, over the shared ports and the user's own ports, or nobody's for None. The trading and the
    valuation operations share the collect and process steps. The order path's wiring is the same for every user, over
    the user's journal and broker; the permissions decide only the broker, the AI limit (in owned_ports) and whether
    run reports reach the LINE recipients. The run records name the AI model owned_ports gave the user.
    """
    owned = dependencies.owned_ports(user)
    notifications = (
        dependencies.notification_provider if user is not None and Permission.NOTIFY_RECIPIENTS in user.permissions else None
    )
    stocks, prices = dependencies.stock_provider, dependencies.price_provider
    journal, broker = owned.journal, broker_for(dependencies, owned, user)
    chat_styler = ChatStylerService(config.sources.line.sentence_endings, config.sources.line.max_message_length)

    return Pipeline(
        strategy_loader=StrategyLoader(owned.technical_settings_repository, config, logger),
        technical_settings_editor=TechnicalSettingsEditor(owned.technical_settings_repository, config),
        run_history=RunHistory(
            journal, market_clock, config, logger, config.ai.model_for(user.ai_model if user is not None else None)
        ),
        account_loader=AccountLoader(broker, stocks, logger),
        market_scanner=MarketScanner(stocks, logger),
        stock_lookup=StockLookup(stocks, logger),
        stock_search=StockSearch(stocks, config),
        most_traded=MostTraded(stocks, config),
        market_breadth_loader=MarketBreadthLoader(stocks, dependencies.fundamentals_provider),
        index_history_loader=IndexHistoryLoader(prices, market_clock, config),
        buzz_scanner=BuzzScanner(dependencies.social_media_provider, stocks, logger, config),
        intraday_candidates=IntradayCandidates(stocks, owned.watchlist_repository, logger),
        data_collector=MarketDataCollector(prices, market_clock, config, logger),
        official_change_feed=OfficialChangeFeed(stocks),
        realtime_quote_feed=RealtimeQuoteFeed(prices, market_clock, config, logger),
        technical_filter=TechnicalFilter(logger),
        indicator_readings=IndicatorReadings(),
        news_feed=NewsFeed(dependencies.news_provider, config, logger),
        ai_analyser=AiAnalyser(owned.ai_provider, owned.knowledge_repository, market_clock, config, logger),
        sentiment_analyser=SentimentAnalyser(owned.sentiment_classifier, config, logger),
        watch_stocks=WatchStocks(owned.watchlist_repository, market_clock, config, logger),
        unwatch_stocks=UnwatchStocks(owned.watchlist_repository, logger),
        account_risk_check=AccountRiskCheck(journal, market_clock, config, logger),
        signals=Signals(journal, market_clock, config, logger),
        manual_signal=ManualSignal(journal, market_clock, config, logger),
        decision_memory=DecisionMemory(owned.knowledge_repository, logger),
        order_preparation=OrderPreparation(journal, market_clock, config, logger),
        order_execution=OrderExecution(broker, journal, market_clock, logger),
        order_outcome=OrderOutcome(broker, journal, market_clock, logger),
        reporting=Reporting(notifications, config, logger),
        run_reports=RunReports(journal, logger),
        recent_runs=RecentRuns(journal),
        run_lookup=RunLookup(journal),
        active_watchlist=ActiveWatchlist(owned.watchlist_repository),
        account_history=AccountHistory(broker, journal, stocks, prices, market_clock, config, logger),
        fundamentals_feed=FundamentalsFeed(dependencies.fundamentals_provider, market_clock, logger),
        market_valuation_loader=MarketValuationLoader(stocks, market_clock, config),
        valuation_appraiser=ValuationAppraiser(config),
        valuation_screener=ValuationScreener(config),
        valuation_explainer=ValuationExplainer(owned.ai_provider, market_clock, config, logger),
        chat_reply=ChatReply(
            dependencies.ai_provider, chat_styler, dependencies.conversation_repository, market_clock, config, logger
        ),
        dispatcher=Dispatcher(dependencies.platform_provider, logger),
        settings_reader=SettingsReader(dependencies.settings_files),
        settings_backups=SettingsBackups(dependencies.settings_files),
        settings_audit=SettingsAudit(dependencies.settings_files, dependencies.user_store),
        settings_editor=SettingsEditor(dependencies.settings_files, config),
        settings_form_editor=SettingsFormEditor(dependencies.settings_files),
        settings_confirmation=SettingsConfirmation(dependencies.user_store, dependencies.attempt_log, market_clock, config, logger),
        settings_save=SettingsSave(dependencies.settings_files, market_clock, logger),
        editor_access=EditorAccess(dependencies.user_store),
        sign_in_options=SignInOptions(dependencies.user_store, config),
        first_administrator_setup=FirstAdministratorSetup(dependencies.user_store, market_clock, LEGACY_OWNER_ID, logger),
        sign_in_attempt=SignInAttempt(dependencies.user_store, dependencies.attempt_log, market_clock, config, logger),
        user_lookup=UserLookup(dependencies.user_store),
        password_reset=PasswordReset(dependencies.user_store, market_clock, logger),
        user_registration=UserRegistration(dependencies.user_store, dependencies.attempt_log, market_clock, config, logger),
        session_start=SessionStart(dependencies.user_store, market_clock, config),
        session_user=SessionUser(dependencies.user_store, market_clock),
        sign_out=SignOut(dependencies.user_store),
        user_directory=UserDirectory(dependencies.user_store),
        user_change=UserChange(dependencies.user_store, market_clock, logger),
        ai_model_lookup=AiModelLookup(config),
        ai_model_choice=AiModelChoice(dependencies.user_store, market_clock, config, logger),
    )


def compose_runtime(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> Runtime:
    signed_out = build_pipeline(config, logger, market_clock, dependencies, None)
    return Runtime(
        pipeline_for=lambda user: build_pipeline(config, logger, market_clock, dependencies, user),
        signed_out=signed_out,
        market_valuation_cache=MarketValuationCache(signed_out.load_market_valuation, config.api.valuation_cache_minutes * 60),
        config=config,
        logger=logger,
    )


STARTUP_REFUSALS = (InvalidSettingsError, OutdatedDatabaseError, TradingSetupError, AccountsSetupError, AccountsKeyError)
"""
What startup_settings and open_runtime raise for a setup they refuse to start with, before any workflow runs. Each
says what to fix, so the CLI, the Web API and the password reset print it alone, with no traceback, and exit 1.
"""


def create_process_state(config: AppConfig) -> ProcessState:
    """The logger at the starting behavior.log_level, an empty attempt log and the caches' write lock, once per process."""
    logger = LoggerService(level=config.behavior.log_level)
    return ProcessState(logger=logger, attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())


@asynccontextmanager
async def open_runtime(config: AppConfig, process: ProcessState) -> AsyncGenerator[Runtime]:
    """
    The whole startup for settings startup_settings passed: the accounts key (secrets/accounts.key created on the first
    start where the environment allows it), the database (opened and brought to the current schema), the broker login,
    every adapter and the check that the key opens the saved users. It raises one of STARTUP_REFUSALS for a setup it
    refuses, before any workflow runs. Whatever it opened closes when the caller is done, or at once when a later step
    fails: the broker logs out, then the database closes.
    """
    accounts_key = load_accounts_key(config, process.logger)
    market_clock = TaiwanMarketClock(config.market_hours)

    async with AsyncExitStack() as opened:
        db = DatabaseConnector(config=config, logger=process.logger)
        opened.push_async_callback(db.close)
        await db.init_db()
        real_broker = await opened.enter_async_context(open_real_broker(config, process.logger))
        dependencies = await build_provider_dependencies(config, db, process, market_clock, accounts_key, real_broker)
        await dependencies.user_store.check_key()
        yield compose_runtime(config, process.logger, market_clock, dependencies)


@asynccontextmanager
async def open_database() -> AsyncGenerator[DatabaseConnector]:
    """
    The configured database alone, for the database commands: no trading check, no accounts key, no broker and no
    startup check, so a database that startup refuses opens too. Raises InvalidSettingsError for settings that do not
    validate.
    """
    config = load_settings(get_project_root())
    database = DatabaseConnector(config=config, logger=LoggerService(level=config.behavior.log_level))

    try:
        yield database

    finally:
        await database.close()
