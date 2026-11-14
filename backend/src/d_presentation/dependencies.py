import asyncio
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import timedelta
from hashlib import sha256
from typing import TYPE_CHECKING, Any

import chromadb
from chromadb.api import ClientAPI
from pydantic import SecretStr

from a_domain.model.system.user import User
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.article_index import IArticleIndex
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.ai.sentiment_classifier import ISentimentClassifier
from a_domain.ports.ai.stock_brief_repository import IStockBriefRepository
from a_domain.ports.ai.system_writing_log import ISystemWritingLog
from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.chat.platform_provider import IPlatformProvider
from a_domain.ports.market.annual_report_provider import IAnnualReportProvider
from a_domain.ports.market.article_store import IArticleStore
from a_domain.ports.market.broker_quote_provider import IBrokerQuoteProvider
from a_domain.ports.market.cached_price_provider import ICachedPriceProvider
from a_domain.ports.market.company_basics_provider import ICompanyBasicsProvider
from a_domain.ports.market.company_profile_repository import ICompanyProfileRepository
from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.market.daily_close_archive import IDailyCloseArchive
from a_domain.ports.market.fundamentals_provider import IFundamentalsProvider
from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.market.news_source import INewsSource
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_feed import IStockFeed
from a_domain.ports.system.attempt_log import IAttemptLog
from a_domain.ports.system.identity_provider import IIdentityProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.notification_provider import INotificationProvider
from a_domain.ports.system.ordering_switch import IOrderingSwitch
from a_domain.ports.system.settings_confirmations import ISettingsConfirmations
from a_domain.ports.system.settings_files import ISettingsFiles
from a_domain.ports.system.user_store import IUserStore
from a_domain.ports.trading.backtest_repository import IBacktestRepository
from a_domain.ports.trading.execution_provider import IBrokerExecutionProvider, IExecutionProvider, ISimulatedExecutionProvider
from a_domain.ports.trading.holding_repository import IHoldingRepository
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.ports.trading.users_stocks import IUsersStocks
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import AiProvider, BriefKind, ExecutionProvider, MarketType, Permission
from a_domain.types.errors import BrokerUnavailable, RealBrokerRefused
from a_domain.types.ids import UserId
from b_application.config.api_config import FeaturesConfig
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import (
    AccountsSetupError,
    InvalidSettingsError,
    TradingSetupError,
    get_project_root,
    load_settings,
)
from b_application.config.trading_config import ShioajiLogin
from b_application.pipeline import Pipeline
from b_application.use_cases.admin.editor_access import EditorAccess
from b_application.use_cases.admin.settings_confirmation import SettingsConfirmation
from b_application.use_cases.admin.settings_editor import SettingsEditor
from b_application.use_cases.admin.settings_reader import SettingsReader
from b_application.use_cases.admin.settings_reauthentication import SettingsReauthentication
from b_application.use_cases.admin.settings_save import SettingsSave
from b_application.use_cases.backtest.backtest_options import BacktestOptions
from b_application.use_cases.backtest.backtest_removal import BacktestRemoval
from b_application.use_cases.backtest.backtest_replay import BacktestReplay
from b_application.use_cases.backtest.backtest_scores import BacktestScores
from b_application.use_cases.backtest.saved_backtests import SavedBacktests
from b_application.use_cases.chat.chat_reply import ChatReply
from b_application.use_cases.chat.dispatcher import Dispatcher
from b_application.use_cases.collect.annual_report_refresh import AnnualReportRefresh
from b_application.use_cases.collect.archive_warm_up import ArchiveWarmUp
from b_application.use_cases.collect.article_refresh_stocks import ArticleRefreshStocks
from b_application.use_cases.collect.article_store_backfill import ArticleStoreBackfill
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.daily_close_archiver import DailyCloseArchiver
from b_application.use_cases.collect.daily_history_backfill import DailyHistoryBackfill
from b_application.use_cases.collect.fundamentals_feed import FundamentalsFeed
from b_application.use_cases.collect.fundamentals_history_backfill import FundamentalsHistoryBackfill
from b_application.use_cases.collect.index_history_loader import IndexHistoryLoader
from b_application.use_cases.collect.intraday_candidates import IntradayCandidates
from b_application.use_cases.collect.main_business_refresh import MainBusinessRefresh
from b_application.use_cases.collect.market_breadth_loader import MarketBreadthLoader
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.collect.most_traded import MostTraded
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.collect.realtime_quote_feed import RealtimeQuoteFeed
from b_application.use_cases.collect.stock_analysis_lookup import StockAnalysisLookup
from b_application.use_cases.collect.stock_lookup import StockLookup
from b_application.use_cases.collect.stock_news_lookup import StockNewsLookup
from b_application.use_cases.collect.stock_search import StockSearch
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.article_indexer import ArticleIndexer
from b_application.use_cases.process.company_background import CompanyBackground
from b_application.use_cases.process.daily_stock_brief import DailyStockBrief
from b_application.use_cases.process.indicator_readings import IndicatorReadings
from b_application.use_cases.process.sentiment_analyser import SentimentAnalyser
from b_application.use_cases.process.stock_brief_context import StockBriefContext
from b_application.use_cases.process.strategy_loader import StrategyLoader
from b_application.use_cases.process.system_writing_stocks import SystemWritingStocks
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.process.technical_settings_editor import TechnicalSettingsEditor
from b_application.use_cases.ranking.latest_ranking import LatestRanking
from b_application.use_cases.ranking.ranking_history_loader import RankingHistoryLoader
from b_application.use_cases.ranking.ranking_replay import RankingReplay
from b_application.use_cases.ranking.ranking_standing import StockRankingStanding
from b_application.use_cases.ship.decision_memory import DecisionMemory
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.run_history import RunHistory
from b_application.use_cases.ship.run_lookup import RunLookup
from b_application.use_cases.ship.run_reports import RunReports
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_history import AccountHistory
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.active_watchlist import ActiveWatchlist
from b_application.use_cases.trade.brokerage_statement import BrokerageStatementReader
from b_application.use_cases.trade.follow_candidates import FollowCandidates
from b_application.use_cases.trade.follow_signals import FollowSignals
from b_application.use_cases.trade.held_positions import HeldPositions
from b_application.use_cases.trade.holding_entry import HoldingEntry
from b_application.use_cases.trade.holding_removal import HoldingRemoval
from b_application.use_cases.trade.holdings_analysis import HoldingsAnalysis
from b_application.use_cases.trade.manual_signal import ManualSignal
from b_application.use_cases.trade.mock_account_reset import MockAccountReset
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.use_cases.trade.order_outcome import OrderOutcome
from b_application.use_cases.trade.order_preparation import OrderPreparation
from b_application.use_cases.trade.ranking_follow_candidates import RankingFollowCandidates
from b_application.use_cases.trade.ranking_follow_return import RankingFollowReturn
from b_application.use_cases.trade.ranking_follow_signals import RankingFollowSignals
from b_application.use_cases.trade.trade_history import TradeHistory
from b_application.use_cases.trade.unwatch_stocks import UnwatchStocks
from b_application.use_cases.trade.watch_stocks import WatchStocks
from b_application.use_cases.users.ai_model_choice import AiModelChoice
from b_application.use_cases.users.ai_model_lookup import AiModelLookup
from b_application.use_cases.users.first_administrator_setup import FirstAdministratorSetup
from b_application.use_cases.users.google_account import GoogleAccount
from b_application.use_cases.users.google_identity_check import GoogleIdentityCheck
from b_application.use_cases.users.google_sign_in_start import GoogleSignInStart
from b_application.use_cases.users.password_reset import PasswordReset
from b_application.use_cases.users.session_start import SessionStart
from b_application.use_cases.users.sign_in_attempt import SignInAttempt
from b_application.use_cases.users.sign_in_options import SignInOptions
from b_application.use_cases.users.sign_out import SignOut
from b_application.use_cases.users.user_change import UserChange
from b_application.use_cases.users.user_directory import UserDirectory
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
from c_infrastructure.ai_models.ai_adapter.system_ai_provider import SystemAiProvider
from c_infrastructure.ai_models.ai_adapter.web_search_adapter import WebSearchAiAdapter
from c_infrastructure.ai_models.onnx_text_embedder import OnnxTextEmbedder
from c_infrastructure.ai_models.sentiment_classifier import AiSentimentClassifier
from c_infrastructure.database.chroma.article_index import ChromaArticleIndex
from c_infrastructure.database.chroma.conversation_repository import ChromaConversationRepository
from c_infrastructure.database.chroma.knowledge_repository import ChromaKnowledgeRepository
from c_infrastructure.database.chroma.schema import ChromaCollection
from c_infrastructure.database.db_connector import DatabaseConnector, OutdatedDatabaseError
from c_infrastructure.database.models.stock_brief_dto import CompanyCardDTO, StockBriefDTO
from c_infrastructure.database.models.user_dto import LEGACY_OWNER_ID, load_accounts_key
from c_infrastructure.database.repositories.article_store import SqlArticleStore
from c_infrastructure.database.repositories.backtest_repository import SqlBacktestRepository
from c_infrastructure.database.repositories.company_profile_repository import SqlCompanyProfileRepository
from c_infrastructure.database.repositories.daily_close_archive import SqlDailyCloseArchive
from c_infrastructure.database.repositories.holding_repository import HoldingRepository
from c_infrastructure.database.repositories.sentiment_repository import SentimentRepository
from c_infrastructure.database.repositories.stock_brief_repository import SqlStockBriefRepository
from c_infrastructure.database.repositories.system_writing_log import SqlSystemWritingLog
from c_infrastructure.database.repositories.trading_journal import TradingJournal
from c_infrastructure.database.repositories.user_store import AccountsKeyError, SqlUserStore
from c_infrastructure.database.repositories.users_stocks import SqlUsersStocks
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.feed.news.cnyes_news_provider import CnyesNewsProvider
from c_infrastructure.feed.news.yahoo_tw_news_provider import YahooTwNewsProvider
from c_infrastructure.feed.news_provider import NewsProvider
from c_infrastructure.feed.ptt_provider import PttProvider
from c_infrastructure.feed.stock_feed import HeldStockFeed
from c_infrastructure.feed.tavily_provider import TavilySearchAdapter
from c_infrastructure.identity.google_identity_provider import GoogleIdentityProvider
from c_infrastructure.market.cached_price_provider import CachedPriceProvider
from c_infrastructure.market.daily_bar_matrix_provider import DailyBarMatrixProvider
from c_infrastructure.market.exchange_daily_reports import ExchangeDailyReports
from c_infrastructure.market.mops_company_basics import MopsCompanyBasicsProvider
from c_infrastructure.market.mops_fundamentals_provider import MopsFundamentalsProvider
from c_infrastructure.market.request_pace import PacedHost, RequestPace, SharedRequestPace
from c_infrastructure.market.twse_annual_report_provider import TwseAnnualReportProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.platforms.line.line_adapter import LinePlatformAdapter
from c_infrastructure.platforms.line.line_notification_adapter import LineNotificationAdapter
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from c_infrastructure.system.chat_styler_service import ChatStylerService
from c_infrastructure.system.logger_service import LoggerService
from c_infrastructure.system.market_clock import TaiwanMarketClock
from c_infrastructure.system.ordering_switch import SettingsFileOrderingSwitch
from c_infrastructure.system.settings_confirmations import MemorySettingsConfirmations
from c_infrastructure.system.settings_files import SettingsFiles
from c_infrastructure.technical.sql_technical_settings_repository import SqlTechnicalSettingsRepository
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider
from d_presentation.web.market_valuation_cache import MarketValuationCache

if TYPE_CHECKING:
    from shioaji import Shioaji

    from c_infrastructure.market.shioaji_quote_provider import ShioajiConnection


type RealBroker = IBrokerExecutionProvider[Any, Any]
"""A real broker whatever its SDK's types: the wiring names none of them."""


@dataclass(frozen=True, slots=True)
class Runtime:
    """
    What the CLI and the Web API run on. pipeline_for(user, broker) is that user's object graph on that broker, the run's
    choice, over the ports that hold that user's data, built per call, so nothing caches one and no role or status
    change waits on a cache: the mock account unless the run chose a real broker, which only a user with
    USE_REAL_BROKER gets (RealBrokerRefused) while its login is up (BrokerUnavailable). signed_out is the graph of
    nobody, built once, for sign-in, setup, the public market pages and LINE chat: its ports that hold users' data refuse
    their first call with SignInRequired, its AI provider among them, so no request made through it spends an AI call.
    open_runtime() builds it from the real adapters; compose_runtime() wires the same graph over any ports, so tests
    and the order-gate check run it over fakes.
    """

    pipeline_for: Callable[[User, ExecutionProvider], Pipeline]
    signed_out: Pipeline
    system_writer: Pipeline | None
    """
    The graph of the site's own writing, which the Web API's timer alone runs (write_for_system_stocks): signed_out
    with its brief and its company card written on the system's provider, whose calls count against
    stock_page.system_writing.daily_ai_calls and are named for no user. No request's dependency answers it, so no
    route spends the system's budget. None while the site's own writing is off.
    """
    market_valuation_cache: MarketValuationCache
    """
    The market valuation this runtime loaded, reused for api.valuation_cache_minutes. It lives and dies with the
    runtime, so its loader and its lifetime always come from the settings the runtime runs on.
    """

    config: AppConfig
    logger: ILoggingProvider
    broker_market_data: bool
    """Whether the runtime's realtime quotes are the broker's: its Shioaji login was up when it opened."""
    shioaji: ShioajiConnection | None
    """The process's Shioaji login of the site's key pair, up or not; None where the site makes none (ProviderDependencies)."""
    real_broker: RealBroker | None
    """SinoPac on the site's login, where the audience offers it and its account check passed (connect_shioaji); else None."""

    def brokers_for(self, user: User) -> list[ExecutionProvider]:
        """What the CLI and the Web offer `user` for a run now (offered_brokers); pipeline_for refuses any other."""
        return offered_brokers(self.real_broker, user, self.config.features)

    @property
    def realtime_quotes(self) -> bool:
        """
        Whether the runtime has a realtime quote to order on now: its market data is the broker's and Shioaji has not
        reported the login down. Without one, Buzz, Intraday and a follow priced on realtime quotes could only refuse
        every order, so the Web API refuses to start them.
        """
        return self.broker_market_data and self.shioaji is not None and self.shioaji.up

    @property
    def login_down(self) -> bool:
        """Whether the site's Shioaji login failed or went down, which the Web API's timer opens a runtime to make again."""
        return self.shioaji is not None and not self.shioaji.up

    def become_current(self) -> None:
        """What the process takes from the settings of the runtime that serves new work: the log level of its one logger."""
        self.logger.set_level(self.config.behavior.log_level)


@dataclass(frozen=True, slots=True)
class ProcessState:
    """
    What one process keeps whichever settings it runs on, handed to every runtime it opens: the logger (loguru is
    process-wide; the current runtime sets its level), the recent sign-in attempts, so no settings change resets the
    attempt limits, the settings confirmations by Google, and the write lock of the shared caches.
    """

    logger: ILoggingProvider
    attempt_log: IAttemptLog
    cache_writes: asyncio.Lock
    """
    One save at a time of the price history, the MOPS EPS pages and the classified posts, across every runtime: a
    retired runtime still finishing a run and the current one would otherwise insert the same row at once.
    """
    exchange_request_paces: dict[MarketType, RequestPace] = field(
        default_factory=lambda: {market: RequestPace() for market in MarketType}
    )
    """The pace of the requests to each exchange's site for a daily report, which every runtime's requests keep."""
    shioaji_connections: dict[ShioajiLogin, ShioajiConnection] = field(default_factory=dict)
    """
    The Shioaji connection of each login the process made: its client, logged in once and again only after the login
    failed or went down, every earlier client, never logged out, and the one request pacer of the login. Every later
    runtime reuses it; shioaji 1.3.1 segfaults at the next garbage collection after a logout.
    """
    settings_confirmations: ISettingsConfirmations = field(default_factory=MemorySettingsConfirmations)
    """The fresh Google authentications granted for a settings save, which a reload of the settings must not forget."""


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
    mock_broker: ISimulatedExecutionProvider
    ai_provider: IAiProvider
    """
    The user's counted provider, on the AI model the user chose while the site offers it, else on ai.active_model,
    capped at accounts.daily_ai_calls unless the user has UNCAPPED_AI. Every paid call of a workflow or an explanation
    goes through it.
    """
    sentiment_classifier: ISentimentClassifier
    backtest_repository: IBacktestRepository
    holding_repository: IHoldingRepository
    """The holdings the user entered by hand."""


@dataclass(slots=True)
class ProviderDependencies:
    """The adapters shared by every owner, built once per process, and the factory of one owner's adapters."""

    stock_provider: TaiwanStockProvider
    price_provider: IOhlcvProvider
    """The daily history and realtime quotes the site may use: the exchanges' history cache, else the open-data archive."""
    history_cache: ICachedPriceProvider | None
    """The exchanges' history cache when price_provider is one, which the Web API's timer refreshes; None for the archive."""
    bar_matrix_provider: IDailyBarMatrixProvider
    """
    price_provider's held history of every listed stock as one matrix, which the backtests of every user read, and the
    monthly ranking's history. It lives with the runtime: each is built at its first read, again when the source holds
    other bars, and anew on new settings.
    """
    stock_brief_repository: IStockBriefRepository
    """The site's AI briefs of stocks, one per stock and Taipei calendar day, shared by every user."""
    company_card_repository: IStockBriefRepository
    """The site's company cards, each under the day it was claimed on, in a table of their own, shared by every user."""
    system_writing_log: ISystemWritingLog
    """The rounds of the site's own writing, one per session, kept across restarts."""
    system_ai_provider: IAiProvider | None
    """
    The provider of the site's own writing, on ai.system_model, its calls counted per day against
    stock_page.system_writing.daily_ai_calls and named for no user. Only Runtime.system_writer's briefs and cards use
    it. None while the site's own writing is off, which builds no adapter for it.
    """
    company_profile_repository: ICompanyProfileRepository
    """What the site holds about each listed company itself, one profile per stock, shared by every user."""
    article_store: IArticleStore
    """What the site read about each stock, kept in the database and shared by every user."""
    article_index: IArticleIndex
    """The article store's vectors, in a Chroma collection of their own, computed by the runtime's own embedding model."""
    users_stocks: IUsersStocks
    """The stocks any user holds or watches, as stock ids alone: the timer keeps their articles current."""
    broker_market_data: bool
    """Whether the site's realtime quotes are its broker login's market data. Without it, no quote is served."""
    shioaji: ShioajiConnection | None
    """
    The process's Shioaji login of the environment's key pair on an audience with realtime quotes, whether it is up or
    not: a login that failed at the start has one too. None on a public site and without the key pair.
    """
    daily_close_archive: IDailyCloseArchive
    fundamentals_provider: IFundamentalsProvider | None
    """MOPS, or None for an audience that reads no MOPS (public): its valuation is refused."""
    company_basics_provider: ICompanyBasicsProvider | None
    """MOPS's company basic information, or None for an audience that reads no MOPS (public): no main business is read."""
    annual_report_provider: IAnnualReportProvider | None
    """The exchange's document site, or None for an audience that reads no annual report (public)."""

    news_provider: INewsProvider
    """The news sites, or the open-data archive's material information for an audience without news articles (public)."""

    social_media_provider: ISocialMediaProvider | None
    """PTT, which Buzz and the stock pages read, or None for an audience without realtime quotes (public), which runs no Buzz."""
    ai_provider: IAiProvider
    """The installation's own provider, on ai.active_model, uncounted. Only LINE chat uses it; LINE chat stays as it is."""
    conversation_repository: IConversationRepository
    notification_provider: INotificationProvider | None
    platform_provider: IPlatformProvider | None
    settings_files: ISettingsFiles
    user_store: IUserStore
    attempt_log: IAttemptLog
    real_broker: RealBroker | None
    """
    SinoPac, on the login connect_shioaji made, where the audience offers it and its account check passed; None
    elsewhere. Only the Pipeline of a run an administrator started on it holds it.
    """
    ordering_switch: IOrderingSwitch
    """Whom the settings files on disk let order on each broker now, which every order of every runtime and process asks."""
    owned_ports: Callable[[User | None], OwnedPorts]
    """A user, or None signed out -> the adapters that hold that user's data. The order-gate check passes fakes."""
    identity_provider: IIdentityProvider | None = None
    """Google, on the client of the environment's GOOGLE_CLIENT_ID; None while the site offers no sign-in with Google."""
    settings_confirmations: ISettingsConfirmations = field(default_factory=MemorySettingsConfirmations)
    """The process's own (ProcessState), so the runtime a settings save opens still holds the grant that confirms it."""


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
    """
    Groq, searching the web first when web search is on and TAVILY_API_KEY and the RAG injection prompt are set. Startup
    refuses web search on an audience without news articles: a search brings news sites' text, which a public site may
    not use.
    """
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


def import_shioaji() -> type[Shioaji]:
    """The SDK's client class, imported with its reporting off unless the environment turns it on (sdk_reporting)."""
    import c_infrastructure.trading.shioaji.sdk_reporting  # noqa: F401

    # isort: split
    from shioaji import Shioaji

    return Shioaji


def site_login(config: AppConfig) -> ShioajiLogin | None:
    """The login the site's market data needs: the environment's key pair on an audience with realtime quotes, else None."""
    return config.shioaji.login(config.environment) if config.audience.realtime_quotes else None


async def connect_shioaji(
    config: AppConfig, process: ProcessState, market_clock: TaiwanMarketClock
) -> tuple[IBrokerQuoteProvider | None, RealBroker | None]:
    """
    The market data and the SinoPac broker of a runtime on the process's Shioaji login. Both read the client of the
    environment's key pair, simulation in dev and test, production in prod, which the process logs in once and every
    later runtime of it reuses, until the login fails or Shioaji reports it down: then the next runtime logs in again on
    a new client (ShioajiQuoteProvider.connect). The broker exists where the audience offers it and its account check
    passes (in prod with the CA certificate the production credentials name); a run uses it only when an administrator
    chooses it.

    An audience without realtime quotes (public) builds no Shioaji adapter. A personal site without the key pair, or
    whose login fails, has no realtime quote and no SinoPac, so nothing is ordered; its daily history still comes from
    the exchanges' reports. An account check that fails leaves the market data and offers no SinoPac.
    """
    logger = process.logger
    login = site_login(config)

    if login is None:
        if config.audience.realtime_quotes:
            logger.warning(f"No Shioaji key pair for environment {config.environment.value}: no realtime quote, so no order")

        return None, None

    client_class = import_shioaji()

    from c_infrastructure.market.shioaji_quote_provider import ShioajiConnection, ShioajiQuoteProvider

    if login not in process.shioaji_connections:
        process.shioaji_connections[login] = ShioajiConnection(client=client_class(simulation=login.simulation))

    connection = process.shioaji_connections[login]
    quotes = ShioajiQuoteProvider(
        connection=connection,
        new_client=lambda: client_class(simulation=login.simulation),
        login=login,
        market_clock=market_clock,
        market_data=config.market_data,
        board_lot_shares=config.market.board_lot_shares,
        logger=logger,
    )
    server, reused = "simulation" if login.simulation else "production", connection.up

    try:
        await quotes.connect()
    except Exception as error:
        logger.warning(f"Shioaji {server} login failed: {error}. No realtime quote, so no order")
        return None, None

    login_line = f"Reused the process's Shioaji {server} login" if reused else f"Logged in to Shioaji {server}"
    logger.info(f"{login_line} for realtime quotes")
    return quotes, await connect_sinopac(config, connection, login, logger)


async def connect_sinopac(
    config: AppConfig, connection: ShioajiConnection, login: ShioajiLogin, logger: ILoggingProvider
) -> RealBroker | None:
    """SinoPac's broker on the login the quotes hold, where the audience offers it and its account check passes, else None."""
    from c_infrastructure.trading.shioaji.execution_provider import ShioajiExecutionProvider

    if ExecutionProvider.SHIOAJI not in config.audience.brokers:
        return None

    broker = ShioajiExecutionProvider(connection=connection, login=login, config=config, logger=logger)
    server = "simulation" if login.simulation else "production"

    try:
        await broker.connect()
    except Exception as error:
        logger.warning(f"SinoPac {server} orders unavailable: {error}. Runs order on the mock account only")
        return None

    logger.info(f"SinoPac {server} connected: an administrator reads its account, and orders on it only as features.* allows")
    return broker


def create_news_provider(
    config: AppConfig, logger: ILoggingProvider, archive: IDailyCloseArchive, market_clock: TaiwanMarketClock
) -> INewsProvider:
    """
    The open-data archive's material information alone for an audience without news articles, which never builds a
    news site's adapter; otherwise the news sites in the order they are asked: cnyes first, then Yahoo for what cnyes
    did not find.
    """
    if not config.audience.news_articles:
        return archive

    sources: tuple[INewsSource, ...] = (
        CnyesNewsProvider(config.sources.news, logger),
        YahooTwNewsProvider(config.sources.news, logger),
    )
    return NewsProvider(sources, config, logger, market_clock)


def create_stock_feed(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> IStockFeed | None:
    """
    The stock pages' held news and posts over the runtime's news sites and board, or None for an audience without news
    articles, whose stock pages read the open-data archive alone. It lives with the runtime, so every user's page and
    the signed-out pages share what was fetched, and a settings change starts it anew.
    """
    if not config.audience.news_articles:
        return None

    return HeldStockFeed(
        news=dependencies.news_provider,
        board=dependencies.social_media_provider,
        market_clock=market_clock,
        freshness=config.stock_page.freshness(),
        held_stocks=config.stock_page.news_held_stocks,
        pause=timedelta(seconds=config.stock_page.article_store.refresh_pause_seconds),
        logger=logger,
    )


def create_fundamentals_provider(
    config: AppConfig, db: DatabaseConnector, process: ProcessState, market_clock: TaiwanMarketClock, listing: TaiwanStockProvider
) -> IFundamentalsProvider | None:
    """
    MOPS's income statements and monthly revenue summaries, or None for an audience that reads no MOPS, which never builds
    its adapter. Each request waits on MOPS's pace in the database, which every runtime and every process shares.
    """
    if not config.audience.mops:
        return None

    return MopsFundamentalsProvider(
        db=db,
        market_clock=market_clock,
        mops=config.sources.mops,
        listing=listing,
        logger=process.logger,
        write_lock=process.cache_writes,
        pace=SharedRequestPace(db, PacedHost.MOPS),
    )


def create_system_ai_provider(
    config: AppConfig,
    db: DatabaseConnector,
    ai_providers: Mapping[AiProvider, IAiProvider],
    market_clock: TaiwanMarketClock,
    logger: ILoggingProvider,
) -> IAiProvider | None:
    """
    The counted provider of the site's own writing over ai.system_model's adapter, the one `ai_providers` holds where a
    user's setting offers that model too. None while stock_page.system_writing.daily_ai_calls is 0.
    """
    if not config.stock_page.system_writing.enabled:
        return None

    return SystemAiProvider(
        ai_providers.get(config.ai.system_model) or create_ai_provider(config, logger, config.ai.system_model),
        db,
        market_clock,
        config.stock_page.system_writing.daily_ai_calls,
    )


def create_company_basics_provider(
    config: AppConfig, db: DatabaseConnector, logger: ILoggingProvider
) -> ICompanyBasicsProvider | None:
    """
    MOPS's company basic information, or None for an audience that reads no MOPS, which never builds its adapter, and
    while the settings name no address for it, as a deployment's older settings file does. Its requests wait on the
    pace the income statements' requests wait on.
    """
    if not config.audience.mops or not config.sources.mops.company_basics_set:
        return None

    return MopsCompanyBasicsProvider(config.sources.mops, SharedRequestPace(db, PacedHost.MOPS), logger)


def create_annual_report_provider(
    config: AppConfig, db: DatabaseConnector, market_clock: TaiwanMarketClock, logger: ILoggingProvider
) -> IAnnualReportProvider | None:
    """
    The exchange's document site, or None for an audience that reads no annual report, which never builds its adapter,
    and while the settings name no address for it, as a deployment's older settings file does. Its requests wait on
    the site's pace in the database, which every runtime and every process shares.
    """
    if not config.audience.annual_reports or not config.sources.annual_reports.addresses_set:
        return None

    pace = SharedRequestPace(db, PacedHost.DOCUMENT_SITE)
    return TwseAnnualReportProvider(config.sources.annual_reports, pace, market_clock, logger)


def create_platform_provider(config: AppConfig, logger: ILoggingProvider) -> IPlatformProvider | None:
    """The LINE chat platform, or None while LINE_CHANNEL_ACCESS_TOKEN is unset: the adapter refuses to build without it."""
    if not config.line.channel_access_token:
        return None

    return LinePlatformAdapter(config=config, logger=logger)


def create_identity_provider(config: AppConfig) -> IIdentityProvider | None:
    """Google as startup_settings checked it: whole, at safe addresses, or not offered at all."""
    accounts = config.accounts

    if not accounts.google_sign_in or accounts.google_client_id is None or accounts.google_client_secret is None:
        return None

    return GoogleIdentityProvider(
        client_id=accounts.google_client_id,
        client_secret=accounts.google_client_secret,
        authorization_endpoint=accounts.google_authorization_endpoint,
        token_endpoint=accounts.google_token_endpoint,
        timeout_seconds=accounts.google_timeout_seconds,
    )


def create_notification_provider(config: AppConfig, logger: ILoggingProvider) -> INotificationProvider | None:
    if not config.notifications.enabled:
        return None

    return LineNotificationAdapter(config=config, logger=logger)


def create_history_cache(
    config: AppConfig,
    db: DatabaseConnector,
    process: ProcessState,
    market_clock: TaiwanMarketClock,
    quotes: IBrokerQuoteProvider | None,
    archive: IDailyCloseArchive,
) -> CachedPriceProvider | None:
    """
    The exchanges' daily reports, kept in the database, with the broker's realtime quotes over the Shioaji login
    connect_shioaji made, or the archive's refusal of every quote without one; None for an open-data audience (public),
    which reads the open-data archive instead.
    """
    if config.audience.open_data_only:
        return None

    return CachedPriceProvider(
        quotes=quotes if quotes is not None else archive,
        source=ExchangeDailyReports(
            feeds=config.sources.exchange.daily_reports,
            ex_right_feed=config.sources.exchange.ex_right_references,
            request_paces=process.exchange_request_paces,
            market_clock=market_clock,
            market_data=config.market_data,
            board_lot_shares=config.market.board_lot_shares,
            logger=process.logger,
        ),
        archive=archive,
        db=db,
        market_clock=market_clock,
        market_data=config.market_data,
        reference_months=config.sources.exchange.ex_right_references.months_per_request,
        logger=process.logger,
        write_lock=process.cache_writes,
    )


async def build_provider_dependencies(
    config: AppConfig,
    db: DatabaseConnector,
    process: ProcessState,
    market_clock: TaiwanMarketClock,
    accounts_key: SecretStr,
    quotes: IBrokerQuoteProvider | None,
    real_broker: RealBroker | None,
) -> ProviderDependencies:
    logger = process.logger
    stock_provider = TaiwanStockProvider(
        exchange=config.sources.exchange, market_clock=market_clock, market_data=config.market_data, logger=logger
    )

    logger.info(f"Opening ChromaDB at: {config.db.chroma_persist_path}")
    chroma_client = chromadb.PersistentClient(path=config.db.chroma_persist_path)

    ai_providers = {provider: create_ai_provider(config, logger, provider) for provider in config.ai.offered_models}
    archive = SqlDailyCloseArchive(db, market_clock, config.sources.exchange, config.analysis.material_information_days, logger)
    history_cache = create_history_cache(config, db, process, market_clock, quotes, archive)
    login = site_login(config)
    price_provider = archive if history_cache is None else history_cache

    return ProviderDependencies(
        stock_provider=stock_provider,
        price_provider=price_provider,
        history_cache=history_cache,
        bar_matrix_provider=DailyBarMatrixProvider(
            stock_provider, price_provider, archive, market_clock, config.ranking.history_rule(), logger
        ),
        stock_brief_repository=SqlStockBriefRepository(db, StockBriefDTO),
        company_card_repository=SqlStockBriefRepository(db, CompanyCardDTO),
        system_writing_log=SqlSystemWritingLog(db),
        system_ai_provider=create_system_ai_provider(config, db, ai_providers, market_clock, logger),
        company_profile_repository=SqlCompanyProfileRepository(db),
        article_store=SqlArticleStore(
            db, market_clock, config.stock_page.article_store.retention(), config.stock_page.article_store.max_per_stock
        ),
        article_index=ChromaArticleIndex(
            chroma_client,
            article_collection(config),
            OnnxTextEmbedder(
                config.stock_page.article_store.embedding, config.project_root / config.folder.embedding_model_dir, logger
            ),
            market_clock,
            config.stock_page.article_store.embedded_length,
        ),
        users_stocks=SqlUsersStocks(db, market_clock),
        broker_market_data=quotes is not None,
        shioaji=process.shioaji_connections.get(login) if login is not None else None,
        daily_close_archive=archive,
        fundamentals_provider=create_fundamentals_provider(config, db, process, market_clock, stock_provider),
        company_basics_provider=create_company_basics_provider(config, db, logger),
        annual_report_provider=create_annual_report_provider(config, db, market_clock, logger),
        news_provider=create_news_provider(config, logger, archive, market_clock),
        social_media_provider=(
            PttProvider(config=config, logger=logger, stock_provider=stock_provider, market_clock=market_clock)
            if config.audience.realtime_quotes
            else None
        ),
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
        identity_provider=create_identity_provider(config),
        settings_confirmations=process.settings_confirmations,
        ordering_switch=SettingsFileOrderingSwitch(config.project_root),
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
            mock_broker=MockExecutionProvider(owners_db, config, market_clock, logger),
            ai_provider=counted,
            sentiment_classifier=AiSentimentClassifier(counted, sentiment_repository, config, logger),
            backtest_repository=SqlBacktestRepository(owners_db),
            holding_repository=HoldingRepository(owners_db),
        )

    return owned_ports


def article_collection(config: AppConfig) -> str:
    """
    The Chroma collection of the article index: stock_articles with a fingerprint of what its vectors depend on, the
    embedding model and how much of an article it reads. Vectors of two models cannot be compared, so a change of
    either starts an empty collection, which fills again from the kept articles; the old one stays until it is deleted.
    """
    store = config.stock_page.article_store
    fingerprint = sha256(f"{store.embedding.identity}/{store.embedded_length}".encode()).hexdigest()[:12]

    return f"{ChromaCollection.STOCK_ARTICLES}-{fingerprint}"


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


def real_broker_holder(user: User | None) -> bool:
    """Whether `user` may hold the site's real broker, to read its account or to order on it: USE_REAL_BROKER."""
    return user is not None and Permission.USE_REAL_BROKER in user.permissions


def offered_brokers(real_broker: RealBroker | None, user: User | None, features: FeaturesConfig) -> list[ExecutionProvider]:
    """
    The brokers `user` may choose for a run now, the mock account first: the site's real broker too for a user with
    USE_REAL_BROKER while its login is up and features.* lets the user order on it. The order gates check all three
    again at each order.
    """
    link = real_broker.link() if real_broker is not None else None

    if link is None or not link.up or user is None or not real_broker_holder(user):
        return [ExecutionProvider.MOCK]

    if not features.visibility(link.broker.ordering_feature).shown_to(user.permissions):
        return [ExecutionProvider.MOCK]

    return [ExecutionProvider.MOCK, link.broker]


def broker_for(
    dependencies: ProviderDependencies, owned: OwnedPorts, user: User | None, broker: ExecutionProvider
) -> IExecutionProvider:
    """
    The broker the run chose or the account page reads: the user's own mock account, or the real broker for a user
    with USE_REAL_BROKER while its login is up, so no other user's Pipeline ever holds it. Holding it grants no order:
    the order gates decide at each send, the site's ordering switch first. A signed-out pipeline holds the mock account
    of nobody, which refuses every call.
    """
    if not broker.real:
        return owned.mock_broker

    if not real_broker_holder(user):
        raise RealBrokerRefused(f"Only an administrator orders on {broker.label} or reads its account.")

    link = dependencies.real_broker.link() if dependencies.real_broker is not None else None

    if dependencies.real_broker is None or link is None or not link.up or link.broker != broker:
        raise BrokerUnavailable(f"{broker.label} has no login up on this site now. Runs order on the mock account.")

    return dependencies.real_broker


def build_pipeline(
    config: AppConfig,
    logger: ILoggingProvider,
    market_clock: TaiwanMarketClock,
    dependencies: ProviderDependencies,
    user: User | None,
    chosen: ExecutionProvider,
    stock_feed: IStockFeed | None,
) -> Pipeline:
    """
    Every use case once, over the shared ports and the user's own ports, or nobody's for None, on the broker the run
    chose (`chosen`). The trading and the valuation operations share the collect and process steps. The order path's
    wiring is the same for every user and broker: the ordering steps hold `chosen`'s broker, and the mock_* steps and
    the ranking follow's hold the user's mock account. The permissions decide whether the user may hold a real broker,
    the AI limit (in owned_ports) and whether run reports reach the LINE recipients. The run records name the AI model
    owned_ports gave the user and the broker chosen.
    """
    owned = dependencies.owned_ports(user)
    notifications = (
        dependencies.notification_provider if user is not None and Permission.NOTIFY_RECIPIENTS in user.permissions else None
    )
    stocks, prices = dependencies.stock_provider, dependencies.price_provider
    history_archive = dependencies.daily_close_archive if config.audience.open_data_only else None
    journal, broker, users = owned.journal, broker_for(dependencies, owned, user, chosen), dependencies.user_store
    ordering = dependencies.ordering_switch
    brokerage = dependencies.real_broker if real_broker_holder(user) else None
    user_id = user.user_id if user is not None else None
    chat_styler = ChatStylerService(config.sources.line.sentence_endings, config.sources.line.max_message_length)
    ai_model = config.ai.offered_models[config.ai.model_for(user.ai_model if user is not None else None)]
    return Pipeline(
        strategy_loader=StrategyLoader(owned.technical_settings_repository, config, logger),
        technical_settings_editor=TechnicalSettingsEditor(owned.technical_settings_repository, config),
        run_history=RunHistory(
            journal, market_clock, config, logger, config.ai.model_for(user.ai_model if user is not None else None), chosen
        ),
        account_loader=AccountLoader(broker, stocks, logger),
        stock_lookup=StockLookup(stocks, logger),
        stock_search=StockSearch(stocks, config),
        most_traded=MostTraded(stocks, config),
        market_breadth_loader=MarketBreadthLoader(stocks),
        index_history_loader=IndexHistoryLoader(prices, market_clock, config),
        buzz_scanner=BuzzScanner(dependencies.social_media_provider, stocks, logger, config),
        intraday_candidates=IntradayCandidates(stocks, owned.watchlist_repository, logger),
        data_collector=MarketDataCollector(prices, stocks, history_archive, market_clock, config, logger),
        daily_close_archiver=DailyCloseArchiver(
            stocks, dependencies.daily_close_archive, dependencies.company_profile_repository, logger
        ),
        daily_history_backfill=DailyHistoryBackfill(dependencies.history_cache, market_clock, config),
        fundamentals_history_backfill=FundamentalsHistoryBackfill(
            dependencies.fundamentals_provider, dependencies.daily_close_archive, market_clock, config, logger
        ),
        archive_warm_up=ArchiveWarmUp(dependencies.daily_close_archive, config),
        stock_analysis_lookup=StockAnalysisLookup(
            dependencies.daily_close_archive, dependencies.fundamentals_provider, market_clock, config
        ),
        stock_news_lookup=StockNewsLookup(dependencies.daily_close_archive, stock_feed, dependencies.article_store, stocks, config),
        article_indexer=ArticleIndexer(dependencies.article_store, dependencies.article_index, config, logger),
        main_business_refresh=MainBusinessRefresh(
            dependencies.company_basics_provider, dependencies.company_profile_repository, market_clock, config, logger
        ),
        annual_report_refresh=AnnualReportRefresh(
            dependencies.annual_report_provider,
            dependencies.company_profile_repository,
            dependencies.article_store,
            market_clock,
            config,
            logger,
        ),
        article_refresh_stocks=ArticleRefreshStocks(dependencies.users_stocks, config, logger),
        article_store_backfill=ArticleStoreBackfill(
            dependencies.daily_close_archive, dependencies.article_store, stocks, market_clock, config, logger
        ),
        system_writing_stocks=SystemWritingStocks(
            prices,
            dependencies.bar_matrix_provider,
            dependencies.system_writing_log,
            dependencies.stock_brief_repository,
            dependencies.users_stocks,
            market_clock,
            config,
            logger,
        ),
        company_background=CompanyBackground(
            dependencies.company_profile_repository, dependencies.article_store, market_clock, config
        ),
        company_card=DailyStockBrief(
            dependencies.company_card_repository, owned.ai_provider, market_clock, config, logger, ai_model, BriefKind.COMPANY
        ),
        stock_brief_context=StockBriefContext(
            stocks, prices, dependencies.article_store, dependencies.article_index, market_clock, config, logger
        ),
        daily_stock_brief=DailyStockBrief(
            dependencies.stock_brief_repository, owned.ai_provider, market_clock, config, logger, ai_model
        ),
        realtime_quote_feed=RealtimeQuoteFeed(prices, market_clock, config, logger),
        technical_filter=TechnicalFilter(logger),
        indicator_readings=IndicatorReadings(),
        news_feed=NewsFeed(dependencies.news_provider, config, logger),
        ai_analyser=AiAnalyser(
            owned.ai_provider, owned.knowledge_repository, dependencies.daily_close_archive, market_clock, config, logger
        ),
        sentiment_analyser=SentimentAnalyser(owned.sentiment_classifier, config, logger),
        watch_stocks=WatchStocks(owned.watchlist_repository, market_clock, config, logger),
        unwatch_stocks=UnwatchStocks(owned.watchlist_repository, logger),
        account_risk_check=AccountRiskCheck(journal, market_clock, config, logger),
        signals=Signals(journal, market_clock, config, logger),
        manual_signal=ManualSignal(journal, market_clock, config, logger),
        decision_memory=DecisionMemory(owned.knowledge_repository, logger),
        order_preparation=OrderPreparation(journal, broker, users, ordering, user_id, market_clock, config, logger),
        order_execution=OrderExecution(broker, journal, users, ordering, user_id, market_clock, config, logger),
        order_outcome=OrderOutcome(broker, journal, market_clock, logger),
        mock_account_loader=AccountLoader(owned.mock_broker, stocks, logger),
        mock_order_preparation=OrderPreparation(journal, owned.mock_broker, users, ordering, user_id, market_clock, config, logger),
        mock_order_execution=OrderExecution(owned.mock_broker, journal, users, ordering, user_id, market_clock, config, logger),
        mock_order_outcome=OrderOutcome(owned.mock_broker, journal, market_clock, logger),
        follow_candidates=FollowCandidates(journal, owned.mock_broker, market_clock, config),
        follow_signals=FollowSignals(journal, market_clock, logger),
        ranking_follow_candidates=RankingFollowCandidates(owned.mock_broker, market_clock, config),
        ranking_follow_signals=RankingFollowSignals(journal, market_clock, config, logger),
        ranking_follow_return=RankingFollowReturn(journal, owned.mock_broker, market_clock, config),
        mock_account_history=AccountHistory(owned.mock_broker, journal, stocks, prices, market_clock, config, logger),
        trade_history=TradeHistory(broker, journal),
        mock_account_reset=MockAccountReset(owned.mock_broker, market_clock),
        brokerage_statement=BrokerageStatementReader(brokerage, market_clock, config),
        held_positions=HeldPositions(owned.holding_repository, owned.mock_broker, brokerage, logger),
        holdings_analysis=HoldingsAnalysis(stocks, dependencies.daily_close_archive, market_clock, config, logger),
        holding_entry=HoldingEntry(owned.holding_repository, market_clock),
        holding_removal=HoldingRemoval(owned.holding_repository),
        reporting=Reporting(notifications, config, logger),
        run_reports=RunReports(journal, logger),
        run_lookup=RunLookup(journal),
        active_watchlist=ActiveWatchlist(owned.watchlist_repository),
        account_history=AccountHistory(broker, journal, stocks, prices, market_clock, config, logger),
        backtest_options=BacktestOptions(prices, config),
        backtest_scores=BacktestScores(dependencies.bar_matrix_provider, config, logger),
        backtest_replay=BacktestReplay(stocks, prices, owned.backtest_repository, market_clock, config, logger),
        saved_backtests=SavedBacktests(owned.backtest_repository),
        backtest_removal=BacktestRemoval(owned.backtest_repository),
        ranking_history_loader=RankingHistoryLoader(dependencies.bar_matrix_provider, logger),
        latest_ranking=LatestRanking(stocks, config),
        ranking_standing=StockRankingStanding(config),
        ranking_replay=RankingReplay(stocks, config, logger),
        fundamentals_feed=FundamentalsFeed(dependencies.fundamentals_provider, stocks, market_clock, logger),
        market_valuation_loader=MarketValuationLoader(stocks, market_clock, config),
        valuation_appraiser=ValuationAppraiser(config),
        valuation_screener=ValuationScreener(config),
        valuation_explainer=ValuationExplainer(owned.ai_provider, market_clock, config, logger),
        chat_reply=ChatReply(
            dependencies.ai_provider, chat_styler, dependencies.conversation_repository, market_clock, config, logger
        ),
        dispatcher=Dispatcher(dependencies.platform_provider, logger),
        settings_reader=SettingsReader(dependencies.settings_files),
        settings_editor=SettingsEditor(dependencies.settings_files, config),
        settings_confirmation=SettingsConfirmation(
            dependencies.user_store, dependencies.attempt_log, dependencies.settings_confirmations, market_clock, config, logger
        ),
        settings_reauthentication=SettingsReauthentication(
            dependencies.user_store, dependencies.settings_confirmations, market_clock, config, logger
        ),
        settings_save=SettingsSave(dependencies.settings_files, market_clock, logger),
        editor_access=EditorAccess(dependencies.user_store, config),
        sign_in_options=SignInOptions(dependencies.user_store, config),
        first_administrator_setup=FirstAdministratorSetup(dependencies.user_store, market_clock, LEGACY_OWNER_ID, logger),
        sign_in_attempt=SignInAttempt(dependencies.user_store, dependencies.attempt_log, market_clock, config, logger),
        google_sign_in_start=GoogleSignInStart(
            dependencies.identity_provider, dependencies.attempt_log, dependencies.user_store, market_clock, config
        ),
        google_identity_check=GoogleIdentityCheck(
            dependencies.identity_provider, dependencies.attempt_log, market_clock, config, logger
        ),
        google_account=GoogleAccount(dependencies.user_store, market_clock, config, LEGACY_OWNER_ID, logger),
        password_reset=PasswordReset(dependencies.user_store, market_clock, logger),
        user_registration=UserRegistration(dependencies.user_store, dependencies.attempt_log, market_clock, config, logger),
        session_start=SessionStart(dependencies.user_store, market_clock, config),
        sign_out=SignOut(dependencies.user_store),
        user_directory=UserDirectory(dependencies.user_store, market_clock),
        user_change=UserChange(dependencies.user_store, market_clock, logger),
        ai_model_lookup=AiModelLookup(config),
        ai_model_choice=AiModelChoice(dependencies.user_store, market_clock, config, logger),
    )


def system_writer_pipeline(
    config: AppConfig,
    logger: ILoggingProvider,
    market_clock: TaiwanMarketClock,
    dependencies: ProviderDependencies,
    signed_out: Pipeline,
) -> Pipeline | None:
    """
    The Pipeline of the site's own writing: `signed_out` with its two writers of AI texts, the company card's and the
    daily brief's, on the system's counted provider and ai.system_model, their claims held by no limit of stocks.
    Every other step is the signed-out graph's, so it holds nobody's data and the mock account of nobody. None while
    the site's own writing is off.
    """
    writer = dependencies.system_ai_provider

    if writer is None:
        return None

    model = config.ai.available_models[config.ai.system_model]
    return replace(
        signed_out,
        company_card=DailyStockBrief(
            dependencies.company_card_repository, writer, market_clock, config, logger, model, BriefKind.COMPANY, for_system=True
        ),
        daily_stock_brief=DailyStockBrief(
            dependencies.stock_brief_repository, writer, market_clock, config, logger, model, for_system=True
        ),
    )


def compose_runtime(
    config: AppConfig, logger: ILoggingProvider, market_clock: TaiwanMarketClock, dependencies: ProviderDependencies
) -> Runtime:
    stock_feed = create_stock_feed(config, logger, market_clock, dependencies)
    signed_out = build_pipeline(config, logger, market_clock, dependencies, None, ExecutionProvider.MOCK, stock_feed)
    return Runtime(
        pipeline_for=lambda user, broker: build_pipeline(config, logger, market_clock, dependencies, user, broker, stock_feed),
        signed_out=signed_out,
        system_writer=system_writer_pipeline(config, logger, market_clock, dependencies, signed_out),
        market_valuation_cache=MarketValuationCache(signed_out.load_market_valuation, config.api.valuation_cache_minutes * 60),
        config=config,
        logger=logger,
        broker_market_data=dependencies.broker_market_data,
        shioaji=dependencies.shioaji,
        real_broker=dependencies.real_broker,
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
async def open_runtime(config: AppConfig, process: ProcessState, *, broker_login: bool = True) -> AsyncGenerator[Runtime]:
    """
    The whole startup for settings startup_settings passed: the accounts key (secrets/accounts.key created on the first
    start where the environment allows it), the database (opened and brought to the current schema), the Shioaji login
    that the realtime quotes and a Shioaji broker share (once per process, see ProcessState.shioaji_connections), every
    adapter and the check that the key opens the saved users. It raises one of STARTUP_REFUSALS for a setup it
    refuses, before any workflow runs. The database closes when the caller is done, or at once when a later step fails.
    Without broker_login it makes no Shioaji login, as a personal site without the key pair: no realtime quote and no
    SinoPac, for a command that reads only the held history.
    """
    accounts_key = load_accounts_key(config, process.logger)
    market_clock = TaiwanMarketClock(config.market_hours)

    async with AsyncExitStack() as opened:
        db = DatabaseConnector(config=config, logger=process.logger)
        opened.push_async_callback(db.close)
        await db.init_db()
        quotes, real_broker = await connect_shioaji(config, process, market_clock) if broker_login else (None, None)
        dependencies = await build_provider_dependencies(config, db, process, market_clock, accounts_key, quotes, real_broker)
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


@asynccontextmanager
async def open_archiver(config: AppConfig) -> AsyncGenerator[DailyCloseArchiver]:
    """
    The archive's one step over the database and the TWSE and TPEX OpenAPI alone, for `just archive-closes`: no broker
    login, no accounts key and no AI key, which a personal setup would otherwise need just to archive. The database is
    opened and brought to the current schema as startup does, so an outdated one raises OutdatedDatabaseError.
    """
    logger = LoggerService(level=config.behavior.log_level)
    market_clock = TaiwanMarketClock(config.market_hours)
    database = DatabaseConnector(config=config, logger=logger)

    try:
        await database.init_db()
        exchange = TaiwanStockProvider(
            exchange=config.sources.exchange, market_clock=market_clock, market_data=config.market_data, logger=logger
        )
        archive = SqlDailyCloseArchive(
            database, market_clock, config.sources.exchange, config.analysis.material_information_days, logger
        )
        yield DailyCloseArchiver(exchange, archive, SqlCompanyProfileRepository(database), logger)

    finally:
        await database.close()
