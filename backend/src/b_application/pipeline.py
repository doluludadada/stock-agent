from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time

from pydantic import PositiveInt, SecretStr

from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.system.user import GoogleConfirmation, SignInFlow, User
from a_domain.model.trading.account import Account, Position
from a_domain.model.trading.backtest import Backtest, BacktestInputs
from a_domain.model.trading.order import Order
from a_domain.model.valuation.scan import MarketValuation, ScanCriteria, ValuationScan
from a_domain.model.valuation.valuation import StockValuation, ValuationReport
from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from a_domain.ports.market.daily_close_archive import IDailyCloseArchive
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.settings_files import SettingChange, SettingField, SettingsEdit
from a_domain.ports.system.user_store import IUserStore
from a_domain.ports.trading.backtest_repository import IBacktestRepository
from a_domain.ports.trading.holding_repository import IHoldingRepository
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.rules.fundamentals.stock_analysis import StockAnalysis
from a_domain.rules.market.breadth import MarketBreadth
from a_domain.rules.system.registration import SignInOffer
from a_domain.rules.technical.strategy import TechnicalSettings
from a_domain.rules.trading.holdings import PortfolioAnalysis
from a_domain.rules.trading.ranking import Ranking
from a_domain.rules.trading.ranking_backtest import RankingBacktest
from a_domain.rules.trading.ranking_standing import RankingStanding
from a_domain.rules.valuation.valuation import ReportSection
from a_domain.types.enums import (
    AiAnalysisFocus,
    AiProvider,
    ExecutionProvider,
    HoldingSource,
    MarketIndex,
    MarketScope,
    Role,
    UserStatus,
    WatchlistType,
    Workflow,
)
from a_domain.types.ids import BacktestId, RunId, SessionToken, UserId
from a_domain.types.values import EmailAddress, FormulaId, NewPassword, PositiveFiniteFloat, Username
from b_application.schemas.backtest import BacktestSetup
from b_application.schemas.collect import (
    ArchivedPeriods,
    ArticleBackfill,
    CompanyBackfill,
    HistoryBackfill,
    HistoryCoverage,
    RealtimeQuotes,
    StockFinancials,
    WorldOverview,
)
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.schemas.process import CompanyFacts, HeldBriefs, StockEvaluation
from b_application.schemas.ranking import FormulaComparison
from b_application.schemas.trade import BrokerageAccount, ManualWatch, RankingFollow, RankingFollowSettings
from b_application.schemas.users import AiModels, GoogleRedirect, SignedIn
from b_application.use_cases.admin.editor_access import EditorAccess
from b_application.use_cases.admin.settings_confirmation import SettingsConfirmation
from b_application.use_cases.admin.settings_editor import SettingsEditor
from b_application.use_cases.admin.settings_reader import SettingsReader
from b_application.use_cases.admin.settings_reauthentication import SettingsReauthentication
from b_application.use_cases.admin.settings_save import SettingsSave
from b_application.use_cases.backtest.backtest_options import BacktestOptions
from b_application.use_cases.backtest.backtest_run import BacktestRun
from b_application.use_cases.chat.chat_reply import ChatReply
from b_application.use_cases.chat.dispatcher import Dispatcher
from b_application.use_cases.collect.annual_report_refresh import AnnualReportRefresh
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
from b_application.use_cases.collect.page_quotes import PageQuotes
from b_application.use_cases.collect.realtime_quote_feed import RealtimeQuoteFeed
from b_application.use_cases.collect.stock_analysis_lookup import StockAnalysisLookup
from b_application.use_cases.collect.stock_lookup import StockLookup
from b_application.use_cases.collect.stock_news_lookup import StockNewsLookup
from b_application.use_cases.collect.stock_search import StockSearch
from b_application.use_cases.collect.world_lookup import WorldLookup
from b_application.use_cases.collect.world_refresh import WorldRefresh
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.article_indexer import ArticleIndexer
from b_application.use_cases.process.brief_lookup import BriefLookup
from b_application.use_cases.process.company_background import CompanyBackground
from b_application.use_cases.process.daily_stock_brief import DailyStockBrief
from b_application.use_cases.process.indicator_readings import IndicatorReadings
from b_application.use_cases.process.sentiment_analyser import SentimentAnalyser
from b_application.use_cases.process.stock_brief_context import StockBriefContext
from b_application.use_cases.process.strategy_loader import StrategyLoader
from b_application.use_cases.process.system_writing_stocks import SystemWritingStocks
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.process.world_brief_context import WorldBriefContext
from b_application.use_cases.ranking.latest_ranking import LatestRanking
from b_application.use_cases.ranking.ranking_evidence import RankingEvidence
from b_application.use_cases.ranking.ranking_history_loader import RankingHistoryLoader
from b_application.use_cases.ranking.ranking_replay import RankingReplay
from b_application.use_cases.ranking.ranking_standing import StockRankingStanding
from b_application.use_cases.ship.recent_runs import RecentRuns
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.run_history import RunHistory
from b_application.use_cases.ship.run_lookup import RunLookup
from b_application.use_cases.ship.run_reports import RunReports
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.abandoned_runs import AbandonedRuns
from b_application.use_cases.trade.account_history import AccountHistory
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.brokerage_statement import BrokerageStatementReader
from b_application.use_cases.trade.follow_candidates import FollowCandidates
from b_application.use_cases.trade.follow_signals import FollowSignals
from b_application.use_cases.trade.held_positions import HeldPositions
from b_application.use_cases.trade.holding_entry import HoldingEntry
from b_application.use_cases.trade.holdings_analysis import HoldingsAnalysis
from b_application.use_cases.trade.manual_signal import ManualSignal
from b_application.use_cases.trade.mock_account_reset import MockAccountReset
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.use_cases.trade.order_outcome import OrderOutcome
from b_application.use_cases.trade.order_preparation import OrderPreparation
from b_application.use_cases.trade.order_settlement import OrderSettlement
from b_application.use_cases.trade.ranking_follow_candidates import RankingFollowCandidates
from b_application.use_cases.trade.ranking_follow_return import RankingFollowReturn
from b_application.use_cases.trade.ranking_follow_schedule import RankingFollowSchedule
from b_application.use_cases.trade.ranking_follow_signals import RankingFollowSignals
from b_application.use_cases.trade.trade_history import TradeHistory
from b_application.use_cases.trade.watch_stocks import WatchStocks
from b_application.use_cases.users.ai_model_choice import AiModelChoice
from b_application.use_cases.users.ai_model_lookup import AiModelLookup
from b_application.use_cases.users.first_administrator_setup import FirstAdministratorSetup
from b_application.use_cases.users.google_account import GoogleAccount
from b_application.use_cases.users.google_identity_check import GoogleIdentityCheck
from b_application.use_cases.users.google_sign_in_start import GoogleSignInStart
from b_application.use_cases.users.ranking_follow_choice import RankingFollowChoice
from b_application.use_cases.users.scheduled_followers import ScheduledFollowers
from b_application.use_cases.users.session_start import SessionStart
from b_application.use_cases.users.sign_in_attempt import SignInAttempt
from b_application.use_cases.users.sign_in_options import SignInOptions
from b_application.use_cases.users.signed_in_user import SignedInUser
from b_application.use_cases.users.user_change import UserChange
from b_application.use_cases.users.user_registration import UserRegistration
from b_application.use_cases.valuation.market_valuation_loader import MarketValuationLoader
from b_application.use_cases.valuation.valuation_appraiser import ValuationAppraiser
from b_application.use_cases.valuation.valuation_explainer import ValuationExplainer
from b_application.use_cases.valuation.valuation_screener import ValuationScreener


@dataclass(slots=True)
class Pipeline:
    """
    Every operation the CLI, the Web API and the LINE webhook start. Each line of an operation names one step, the
    values it reads from the run's PipelineStatus and the field that keeps what it returns. An operation asks an AI,
    records a run or sends an order only where its lines call the step that does, so no operation's docstring says what
    it does not do.

    A trading operation loads its technical strategy before its run record exists, so invalid settings stop a run that
    never started. It then runs inside RunHistory.execute.

    Buzz, Intraday, manual BUY and both follows send orders with the same four lines, one decision at a time in decision
    order. OrderPreparation gates the order and records it, OrderExecution sends it, OrderOutcome takes a fill into the
    account, and the order joins status.orders before the next decision, so no decision gets a second order. On a real
    broker a run first settles the orders that ended runs left UNCONFIRMED, and after its last order it settles its own
    (OrderSettlement).

    dependencies.py builds this Pipeline for one run's broker and one signed-in user, or for nobody, whose ports of a
    user's data refuse with SignInRequired. The ordering steps (account_loader, order_preparation, order_execution,
    order_outcome) hold the run's broker, which is the mock account unless an administrator chose a real broker. The
    mock_* steps always hold the user's mock account, and a follow of a run uses only them. A ranking follow orders on a
    real broker only on its simulation server (SimulationOnlyRule).
    """

    strategy_loader: StrategyLoader
    technical_settings_repository: ITechnicalSettingsRepository
    run_history: RunHistory
    account_loader: AccountLoader
    stock_lookup: StockLookup
    stock_search: StockSearch
    most_traded: MostTraded
    page_quotes: PageQuotes
    market_breadth_loader: MarketBreadthLoader
    index_history_loader: IndexHistoryLoader
    buzz_scanner: BuzzScanner
    intraday_candidates: IntradayCandidates
    data_collector: MarketDataCollector
    daily_close_archiver: DailyCloseArchiver
    daily_history_backfill: DailyHistoryBackfill
    fundamentals_history_backfill: FundamentalsHistoryBackfill
    daily_close_archive: IDailyCloseArchive
    stock_analysis_lookup: StockAnalysisLookup
    stock_news_lookup: StockNewsLookup
    article_indexer: ArticleIndexer
    article_refresh_stocks: ArticleRefreshStocks
    article_store_backfill: ArticleStoreBackfill
    main_business_refresh: MainBusinessRefresh
    annual_report_refresh: AnnualReportRefresh
    system_writing_stocks: SystemWritingStocks
    world_refresh: WorldRefresh
    world_lookup: WorldLookup
    world_brief_context: WorldBriefContext
    world_brief: DailyStockBrief
    company_background: CompanyBackground
    company_card: DailyStockBrief
    company_card_lookup: BriefLookup
    stock_brief_context: StockBriefContext
    daily_stock_brief: DailyStockBrief
    stock_brief_lookup: BriefLookup
    realtime_quote_feed: RealtimeQuoteFeed
    technical_filter: TechnicalFilter
    indicator_readings: IndicatorReadings
    news_feed: NewsFeed
    ai_analyser: AiAnalyser
    sentiment_analyser: SentimentAnalyser
    watch_stocks: WatchStocks
    watchlist_repository: IWatchlistRepository
    account_risk_check: AccountRiskCheck
    signals: Signals
    manual_signal: ManualSignal
    order_preparation: OrderPreparation
    order_execution: OrderExecution
    order_outcome: OrderOutcome
    order_settlement: OrderSettlement
    abandoned_runs: AbandonedRuns
    mock_account_loader: AccountLoader
    mock_order_preparation: OrderPreparation
    mock_order_execution: OrderExecution
    mock_order_outcome: OrderOutcome
    follow_candidates: FollowCandidates
    follow_signals: FollowSignals
    ranking_follow_candidates: RankingFollowCandidates
    ranking_follow_signals: RankingFollowSignals
    ranking_follow_return: RankingFollowReturn
    ranking_follow_schedule: RankingFollowSchedule
    ranking_follow_choice: RankingFollowChoice
    scheduled_followers: ScheduledFollowers
    mock_account_history: AccountHistory
    trade_history: TradeHistory
    mock_account_reset: MockAccountReset
    brokerage_statement: BrokerageStatementReader
    held_positions: HeldPositions
    holdings_analysis: HoldingsAnalysis
    holding_entry: HoldingEntry
    holding_repository: IHoldingRepository
    reporting: Reporting
    run_reports: RunReports
    recent_runs: RecentRuns
    run_lookup: RunLookup
    account_history: AccountHistory
    backtest_options: BacktestOptions
    backtest_run: BacktestRun
    backtest_repository: IBacktestRepository
    ranking_history_loader: RankingHistoryLoader
    latest_ranking: LatestRanking
    ranking_standing: StockRankingStanding
    ranking_replay: RankingReplay
    ranking_evidence: RankingEvidence
    fundamentals_feed: FundamentalsFeed
    market_valuation_loader: MarketValuationLoader
    valuation_appraiser: ValuationAppraiser
    valuation_screener: ValuationScreener
    valuation_explainer: ValuationExplainer
    chat_reply: ChatReply
    dispatcher: Dispatcher
    settings_reader: SettingsReader
    settings_editor: SettingsEditor
    settings_confirmation: SettingsConfirmation
    settings_reauthentication: SettingsReauthentication
    settings_save: SettingsSave
    editor_access: EditorAccess
    sign_in_options: SignInOptions
    first_administrator_setup: FirstAdministratorSetup
    sign_in_attempt: SignInAttempt
    google_sign_in_start: GoogleSignInStart
    google_identity_check: GoogleIdentityCheck
    google_account: GoogleAccount
    user_registration: UserRegistration
    session_start: SessionStart
    signed_in_user: SignedInUser
    user_store: IUserStore
    market_clock: IMarketClock
    user_change: UserChange
    ai_model_lookup: AiModelLookup
    ai_model_choice: AiModelChoice

    async def run_full_cycle(self, run_id: RunId | None = None, built_in_strategy_id: str | None = None) -> PipelineStatus:
        """After-market analysis of the whole market. Its decisions are priced from daily closes."""
        strategy = await self.strategy_loader.execute(Workflow.FULL_CYCLE, built_in_strategy_id)

        async with self.run_history.execute(Workflow.FULL_CYCLE, run_id) as stats:
            status = PipelineStatus(stats=stats)
            status.account, status.held_stocks = await self.account_loader.execute(status.stocks)
            status.universe_stocks = await self.stock_lookup.execute(None, status.stats)
            await self.data_collector.execute(status.universe_stocks, strategy.required_bars, status.stats)
            status.survivors = self.technical_filter.execute(status.universe_stocks, strategy, status.stats)
            await self.news_feed.execute(status.survivors, status.stats)
            await self.ai_analyser.execute(status.survivors, AiAnalysisFocus.FUNDAMENTAL, status.stats)
            await self.watch_stocks.execute(status.survivors, WatchlistType.TECHNICAL)
            status.equity, status.risk_blocked_stock_ids, status.signals = await self.account_risk_check.execute(
                status.account, status.held_stocks, status.stocks, status.stale_stock_ids, status.stats
            )
            equity = status.require_equity()
            status.signals += await self.signals.execute(
                status.survivors, status.account, equity, status.risk_blocked_stock_ids, status.stale_stock_ids, status.stats
            )
            await self.reporting.execute(status.signals, status.stats)

        return status

    async def run_buzz_scan(self, run_id: RunId | None = None, built_in_strategy_id: str | None = None) -> PipelineStatus:
        """
        Social momentum. Stop-loss SELLs go first, while their quotes are fresh. Every buzz stock is screened, so one
        without daily history gets a failing report. Sentiment is report only, so it runs after every trading step.
        """
        strategy = await self.strategy_loader.execute(Workflow.BUZZ_SCAN, built_in_strategy_id)

        async with self.run_history.execute(Workflow.BUZZ_SCAN, run_id) as stats:
            status = PipelineStatus(stats=stats)
            await self.order_settlement.execute(status.stats)
            status.account, status.held_stocks = await self.account_loader.execute(status.stocks)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(status.held_stocks, status.stale_stock_ids, status.stats)
            status.equity, status.risk_blocked_stock_ids, status.signals = await self.account_risk_check.execute(
                status.account, status.held_stocks, status.stocks, status.stale_stock_ids, status.stats
            )
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.equity, status.stats):
                    order = await self.order_execution.execute(order, status.stats)
                    status.account = await self.order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)
            status.buzz_stocks = await self.buzz_scanner.execute(status.stocks, status.stats)
            await self.data_collector.execute(status.buzz_stocks, strategy.required_bars, status.stats)
            status.survivors = self.technical_filter.execute(status.buzz_stocks, strategy, status.stats)
            await self.watch_stocks.execute(status.survivors, WatchlistType.BUZZ)
            await self.news_feed.execute(status.survivors, status.stats)
            await self.ai_analyser.execute(status.survivors, AiAnalysisFocus.MOMENTUM, status.stats)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(status.survivors, status.stale_stock_ids, status.stats)
            equity = status.require_equity()
            status.signals += await self.signals.execute(
                status.survivors, status.account, equity, status.risk_blocked_stock_ids, status.stale_stock_ids, status.stats
            )
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.equity, status.stats):
                    order = await self.order_execution.execute(order, status.stats)
                    status.account = await self.order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)
            status.orders = await self.order_settlement.execute(status.stats, status.orders)
            status.sentiment_by_stock_id = await self.sentiment_analyser.execute(status.buzz_stocks, status.stats)
            await self.reporting.execute(status.signals, status.stats)

        return status

    async def run_intraday(self, run_id: RunId | None = None, built_in_strategy_id: str | None = None) -> PipelineStatus:
        """
        Revalidates the held and watched stocks. Stop-loss SELLs go first, while their quotes are fresh. A stock the run
        stopped out or could not quote is analysed no further, and every held stock screened gets its exit decided.
        """
        strategy = await self.strategy_loader.execute(Workflow.INTRADAY, built_in_strategy_id)

        async with self.run_history.execute(Workflow.INTRADAY, run_id) as stats:
            status = PipelineStatus(stats=stats)
            await self.order_settlement.execute(status.stats)
            status.account, status.held_stocks = await self.account_loader.execute(status.stocks)
            status.candidates = await self.intraday_candidates.execute(status.held_stocks, status.stats)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(status.candidates, status.stale_stock_ids, status.stats)
            status.equity, status.risk_blocked_stock_ids, status.signals = await self.account_risk_check.execute(
                status.account, status.held_stocks, status.stocks, status.stale_stock_ids, status.stats
            )
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.equity, status.stats):
                    order = await self.order_execution.execute(order, status.stats)
                    status.account = await self.order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)
            status.technical_candidates = await self.data_collector.execute(
                status.candidates, strategy.required_bars, status.stats, skip=status.blocked_stock_ids
            )
            status.survivors = self.technical_filter.execute(
                status.technical_candidates, strategy, status.stats, keep=status.held_stocks
            )
            await self.news_feed.execute(status.survivors, status.stats)
            await self.ai_analyser.execute(status.survivors, AiAnalysisFocus.FUNDAMENTAL, status.stats)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(status.survivors, status.stale_stock_ids, status.stats)
            equity = status.require_equity()
            status.signals += await self.signals.execute(
                status.survivors, status.account, equity, status.risk_blocked_stock_ids, status.stale_stock_ids, status.stats
            )
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.equity, status.stats):
                    order = await self.order_execution.execute(order, status.stats)
                    status.account = await self.order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)
            status.orders = await self.order_settlement.execute(status.stats, status.orders)
            await self.reporting.execute(status.signals, status.stats)

        return status

    async def analyse_specific_stocks(
        self, stock_ids: list[str], run_id: RunId | None = None, built_in_strategy_id: str | None = None
    ) -> PipelineStatus:
        """
        Complete reports for the stocks the user asked for. Each goes through news and AI whatever its technical
        verdict, so the user can review it before a manual BUY. One without daily history gets a failing report.
        """
        strategy = await self.strategy_loader.execute(Workflow.SPECIFIC_STOCKS, built_in_strategy_id)

        async with self.run_history.execute(Workflow.SPECIFIC_STOCKS, run_id) as stats:
            status = PipelineStatus(stats=stats)
            status.manual_stocks = await self.stock_lookup.execute(stock_ids, status.stats)

            if not status.manual_stocks:
                return status

            await self.data_collector.execute(status.manual_stocks, strategy.required_bars, status.stats)
            status.survivors = self.technical_filter.execute(status.manual_stocks, strategy, status.stats)
            await self.news_feed.execute(status.manual_stocks, status.stats)
            await self.ai_analyser.execute(status.manual_stocks, AiAnalysisFocus.FUNDAMENTAL, status.stats)
            await self.run_reports.execute(status.manual_stocks, status.stats)

        return status

    async def buy_manually(self, stock: Stock, quantity: PositiveInt | None = None, run_id: RunId | None = None) -> PipelineStatus:
        """
        The user's confirmed BUY of one analysed stock, as its own recorded run (ManualSignal).
        status.manual_buy_refusal says why no order was sent; otherwise status.orders holds the one order.
        """
        async with self.run_history.execute(Workflow.MANUAL_BUY, run_id) as stats:
            status = PipelineStatus(stats=stats, manual_stocks=[stock])
            await self.order_settlement.execute(status.stats)
            status.account, status.held_stocks = await self.account_loader.execute(status.stocks)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(status.manual_stocks, status.stale_stock_ids, status.stats)
            status.equity, status.signals, status.manual_buy_refusal = await self.manual_signal.execute(
                stock, quantity, status.account, status.stocks, status.stats
            )
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.equity, status.stats):
                    order = await self.order_execution.execute(order, status.stats)
                    status.account = await self.order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)
            status.orders = await self.order_settlement.execute(status.stats, status.orders)

        return status

    async def follow_run(self, followed_run_id: RunId, run_id: RunId | None = None) -> PipelineStatus:
        """
        The user's follow of one of their finished runs into their mock account, as its own recorded run. A follow that
        FollowCandidates refuses records the refusal and sends nothing.
        """
        async with self.run_history.execute(Workflow.FOLLOW, run_id, followed_run_id) as stats:
            status = PipelineStatus(stats=stats)
            (
                status.followed_run,
                status.followable_signals,
                status.follows,
                status.follow_refusal,
            ) = await self.follow_candidates.execute(followed_run_id)

            if status.follow_refusal is not None:
                return status

            status.manual_stocks = await self.stock_lookup.execute(status.followable_stock_ids, status.stats)
            status.account, status.held_stocks = await self.mock_account_loader.execute(status.stocks)
            await self.data_collector.execute(status.manual_stocks, 1, status.stats)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(status.manual_stocks, status.stale_stock_ids, status.stats)
            status.signals = await self.follow_signals.execute(status.followable_signals, status.stocks, status.account, status.stats)
            for signal in status.signals:
                if order := await self.mock_order_preparation.execute(signal, status.orders, status.equity, status.stats):
                    order = await self.mock_order_execution.execute(order, status.stats)
                    status.account = await self.mock_order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)

        return status

    async def load_follow(self, run_id: RunId) -> PipelineStatus:
        """The run page's follow panel, and the check before a follow starts, as FollowCandidates answers them."""
        status = PipelineStatus.read_only(Workflow.FOLLOW)
        status.followed_run, status.followable_signals, status.follows, status.follow_refusal = await self.follow_candidates.execute(
            run_id
        )

        return status

    async def follow_ranking(self, user: User, run_id: RunId | None = None, *, scheduled: bool = False) -> PipelineStatus:
        """
        The user's follow of the monthly ranking's latest decision on their follow account, as its own recorded run.
        RankingUnavailable without a decision session. FollowAccountChanged when the run is on another account.
        """
        async with self.run_history.execute(Workflow.RANKING_FOLLOW, run_id, scheduled=scheduled) as stats:
            status = PipelineStatus(stats=stats)
            settings = await self.ranking_follow_schedule.execute(user)
            history = await self.ranking_history_loader.execute()
            ranking = await self.latest_ranking.execute(history)
            holdings, status.follow_refusal = await self.ranking_follow_candidates.execute(
                settings.account, ranking, settings.schedule.switched_from, status.stats
            )

            if settings.account.refusal is not None or status.follow_refusal is not None:
                return status

            await self.order_settlement.execute(status.stats)
            status.manual_stocks = await self.stock_lookup.execute(holdings.lacking, status.stats)
            status.account, status.held_stocks = await self.account_loader.execute(status.stocks)
            traded = [*status.held_stocks, *status.manual_stocks]
            await self.data_collector.execute(traded, 1, status.stats)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(traded, status.stale_stock_ids, status.stats)
            status.equity, status.signals = await self.ranking_follow_signals.execute(
                ranking, status.stocks, status.account, settings.schedule.switched_from, status.stats
            )
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.equity, status.stats):
                    order = await self.order_execution.execute(order, status.stats)
                    status.account = await self.order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)
            status.orders = await self.order_settlement.execute(status.stats, status.orders)
            await self.ranking_follow_candidates.execute(
                settings.account, ranking, settings.schedule.switched_from, status.stats, status.stocks, status.equity
            )

        return status

    async def load_ranking_follow(self, user: User) -> RankingFollow:
        """
        The ranking page's follow block and the check before a ranking follow starts, with the mock account's return
        while the follow account is measured (FollowAccount.measured). RankingUnavailable without a decision session.
        """
        settings = await self.ranking_follow_schedule.execute(user)
        history = await self.ranking_history_loader.execute()
        ranking = await self.latest_ranking.execute(history)
        holdings, refusal = await self.ranking_follow_candidates.execute(settings.account, ranking, settings.schedule.switched_from)

        if not settings.account.measured:
            return RankingFollow(settings, holdings, refusal, None)

        mock_account, _, curve, _ = await self.mock_account_history.execute(None, None)
        performance = await self.ranking_follow_return.execute(history, mock_account, curve)

        return RankingFollow(settings, holdings, refusal, performance)

    async def load_follow_schedule(self, user: User) -> RankingFollowSettings:
        """My settings' ranking follow, and the timer's question for one user, as RankingFollowSchedule answers them."""
        return await self.ranking_follow_schedule.execute(user)

    async def choose_ranking_follow(self, user: User, follow_time: time | None, broker: ExecutionProvider) -> User:
        """
        My settings' save of the user's follow account and follow time, None for no schedule, answering the user.
        FollowBrokerNotOffered or FollowTimeNotOffered, saving nothing, for an account or time the site does not offer.
        """
        settings = await self.ranking_follow_schedule.execute(user)

        return await self.ranking_follow_choice.execute(user, follow_time, broker, settings.account)

    async def load_scheduled_followers(self) -> list[User]:
        """The users whose scheduled ranking follow may run now, for the Web API's timer."""
        return await self.scheduled_followers.execute()

    async def settle_orders(self) -> list[Order]:
        """For the Web API's timer, ends abandoned runs and settles the UNCONFIRMED orders of this user's runs on the real broker."""
        await self.abandoned_runs.execute()
        return await self.order_settlement.execute(None)

    async def load_trades(self, limit: int, offset: int) -> list[tuple[Order, SystemStats]]:
        """The account page's trades since the mock account opened, newest first, each with the run whose decision it carried out."""
        return await self.trade_history.execute(limit, offset)

    async def reset_mock_account(self, initial_cash: PositiveFiniteFloat) -> Account:
        """My settings' reset: the user's mock account opens again with `initial_cash` and no positions."""
        return await self.mock_account_reset.execute(initial_cash)

    async def load_brokerage_statement(self) -> BrokerageAccount:
        """The SinoPac page's account as the real broker reports it now, and why its login could not switch servers."""
        return await self.brokerage_statement.execute()

    async def load_holdings(self, sources: frozenset[HoldingSource]) -> PortfolioAnalysis:
        """
        The My holdings page's portfolio of what the user holds under each of `sources` it could read, each stock with
        its ranking standing. RankingUnavailable without a decision session.
        """
        held = await self.held_positions.execute(sources)
        history = await self.ranking_history_loader.execute()
        stock_ids = {position.stock_id for positions in held.values() for position in positions}
        standings = await self.ranking_standing.execute(history, stock_ids)

        return await self.holdings_analysis.execute(held, history, standings)

    async def enter_holding(
        self, stock_id: str, quantity: PositiveInt, average_cost: PositiveFiniteFloat, opened_on: date | None
    ) -> Position | None:
        """The My holdings page's hand-entered holding. None, and nothing kept, when the listing has no such stock."""
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.manual_stocks = await self.stock_lookup.execute([stock_id], status.stats)

        if not status.manual_stocks:
            return None

        return await self.holding_entry.execute(status.manual_stocks[0], quantity, average_cost, opened_on)

    async def remove_holding(self, stock_id: str) -> bool:
        """The My holdings page's removal of a hand-entered holding. False when the stock had none."""
        return await self.holding_repository.remove(stock_id)

    async def watch_manually(self, stock_ids: list[str]) -> ManualWatch:
        """Menu 4 and the watchlist endpoint's MANUAL watch. When the listing lacks an id, nothing is added."""
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.manual_stocks = await self.stock_lookup.execute(stock_ids, status.stats)

        if len(status.manual_stocks) < len(set(stock_ids)):
            return ManualWatch(status.manual_stocks, None)

        return ManualWatch(status.manual_stocks, await self.watch_stocks.execute(status.manual_stocks, WatchlistType.MANUAL))

    async def unwatch_manually(self, stock_ids: list[str]) -> list[str]:
        """The watchlist endpoint's removal: only MANUAL entries go; it returns the stocks that had one."""
        return await self.watchlist_repository.remove(stock_ids, WatchlistType.MANUAL)

    async def load_watchlist(self) -> PipelineStatus:
        """The watchlist endpoint's active entries and the listing that names them; a listing outage leaves them unnamed."""
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.watchlist = await self.watchlist_repository.get_active()
        status.universe_stocks = await self.stock_lookup.execute(None, status.stats)

        return status

    async def load_runs(self, limit: int, offset: int) -> list[SystemStats]:
        """The runs endpoint: `limit` recorded runs, newest first, after the `offset` newest, whichever entry point started them."""
        return await self.recent_runs.execute(limit, offset)

    async def load_run(self, run_id: RunId) -> PipelineStatus | None:
        """One recorded run as its status, its specific-stock reports as manual_stocks. None when the journal holds no such run."""
        run = await self.run_lookup.execute(run_id)

        if run is None:
            return None

        record, reports, signals, orders = run

        return PipelineStatus(stats=record, manual_stocks=reports, signals=signals, orders=orders)

    async def load_account_history(self, as_of: date | None, since: date | None = None) -> PipelineStatus:
        """The account now, its equity curve from `since` on, and the account as of `as_of`, for menu 7 and the account endpoint."""
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.account, status.held_stocks, status.equity_curve, status.account_as_of = await self.account_history.execute(
            as_of, since
        )

        return status

    async def load_backtest_options(self, built_in_strategy_id: str | None = None) -> BacktestSetup:
        """The backtest page's strategy and the inputs of the longest backtest the held history allows, None while it allows none."""
        strategy = await self.strategy_loader.execute(Workflow.RESEARCH, built_in_strategy_id)

        return BacktestSetup(strategy, await self.backtest_options.execute(strategy))

    async def run_backtest(self, inputs: BacktestInputs, built_in_strategy_id: str | None = None) -> Backtest:
        """Replays the strategy over `inputs` and saves the result. BacktestPeriodUnavailable outside the held history."""
        strategy = await self.strategy_loader.execute(Workflow.RESEARCH, built_in_strategy_id)

        return await self.backtest_run.execute(strategy, inputs)

    async def load_ranking(self, formula_name: FormulaId | None = None) -> Ranking:
        """The monthly ranking by the formula named, else the active one. RankingUnavailable without a decision session."""
        history = await self.ranking_history_loader.execute()

        return await self.latest_ranking.execute(history, formula_name=formula_name)

    async def load_ranking_standing(self, stock_id: str) -> RankingStanding:
        """
        The stock page's standing of the stock in the ranking load_ranking answers, or why it is left out.
        RankingUnavailable without a decision session.
        """
        history = await self.ranking_history_loader.execute()

        standings = await self.ranking_standing.execute(history, [stock_id])

        return standings[stock_id]

    async def run_ranking_backtest(self, first: date, last: date, formula_name: FormulaId | None = None) -> RankingBacktest:
        """The ranking replayed from `first` to `last` against its benchmark. BacktestPeriodUnavailable without a decision session."""
        history = await self.ranking_history_loader.execute()

        return await self.ranking_replay.execute(history, first, last, formula_name)

    async def compare_ranking_formulas(self, first: date, last: date) -> FormulaComparison:
        """
        Every formula replayed over one period, and again at the liquidity floor. BacktestPeriodUnavailable for a period
        without a decision session.
        """
        history = await self.ranking_history_loader.execute()

        return await self.ranking_evidence.execute(history, first, last)

    async def load_backtests(self) -> list[Backtest]:
        """The user's saved backtests, newest first."""
        return await self.backtest_repository.saved()

    async def load_backtest(self, backtest_id: BacktestId) -> Backtest | None:
        """One of the user's saved backtests; None when the user has none of that id."""
        return await self.backtest_repository.get(backtest_id)

    async def delete_backtest(self, backtest_id: BacktestId) -> bool:
        """Deletes one of the user's saved backtests, and answers whether the user had one of that id."""
        return await self.backtest_repository.delete(backtest_id)

    async def load_market_valuation(self) -> MarketValuation:
        """Every listed and OTC stock with its official close, TTM EPS and industry; the steps' errors become source warnings."""
        status = PipelineStatus.read_only(Workflow.VALUATION)
        status.universe_stocks = await self.stock_lookup.execute(None, status.stats)
        await self.fundamentals_feed.execute(status.universe_stocks, status.stats)

        return await self.market_valuation_loader.execute(status.universe_stocks, status.stats)

    def appraise_valuations(
        self, valuations: Sequence[StockValuation], target_pe: PositiveFiniteFloat | None
    ) -> list[ValuationReport]:
        """Menu 5's chosen stocks, each valued at the user's target P/E, in the order chosen."""
        return self.valuation_appraiser.execute(valuations, target_pe)

    def screen_valuation(self, market: MarketValuation, criteria: ScanCriteria) -> ValuationScan:
        """The undervalued scan's valuation step at the user's criteria."""
        return self.valuation_screener.execute(market, criteria)

    async def confirm_valuation_technical(self, scan: ValuationScan, built_in_strategy_id: str | None = None) -> ValuationScan:
        """The undervalued scan's second step: the active technical strategy, applied exactly as the trading workflows apply it."""
        strategy = await self.strategy_loader.execute(Workflow.VALUATION, built_in_strategy_id)
        status = PipelineStatus.read_only(Workflow.VALUATION)
        status.technical_candidates = await self.data_collector.execute(scan.survivor_stocks, strategy.required_bars, status.stats)
        status.survivors = self.technical_filter.execute(status.technical_candidates, strategy, status.stats)

        return scan.after_technical_step(strategy.strategy_id)

    async def explain_valuation(self, report: ValuationReport) -> list[ReportSection]:
        """The domain computed every number; the AI explains them with the stock's news."""
        status = PipelineStatus.read_only(Workflow.VALUATION)
        await self.news_feed.execute([report.stock], status.stats)

        return await self.valuation_explainer.execute(report)

    async def search_stocks(self, query: str) -> list[Stock]:
        """The stock search: listed stocks by code or name, with their latest official close."""
        return await self.stock_search.execute(query)

    async def load_most_traded(self) -> list[Stock]:
        """The market overview: the latest session's most traded stocks in the exchange listing."""
        return await self.most_traded.execute()

    async def load_page_quotes(self, stock_ids: list[str], indexes: list[MarketIndex]) -> RealtimeQuotes:
        """The pages' realtime quotes of these stocks and indexes from the shared board, and when a page asks again."""
        return await self.page_quotes.execute(stock_ids, indexes)

    async def archive_daily_closes(self) -> ArchivedPeriods:
        """For the Web API's timer, saves what the TWSE and TPEX OpenAPI serve now and answers what the archive holds."""
        return await self.daily_close_archiver.execute()

    async def refresh_daily_history(self) -> HistoryCoverage | None:
        """For the Web API's timer, brings the history cache up to the last settled session. None on a public site."""
        return await self.daily_history_backfill.execute()

    async def backfill_history(self, first: date) -> HistoryBackfill:
        """
        For `just backfill-history`, the daily history, monthly revenue and EPS back to `first`. Each part saves what it
        fetched as it comes, so a rerun fetches only what is missing.
        """
        revenue, eps = await self.fundamentals_history_backfill.execute(first)
        history = await self.daily_history_backfill.execute(first)

        return HistoryBackfill(history, revenue, eps)

    async def load_financials(self, stock_id: str) -> StockFinancials:
        """A stock's page: its archived quarters' figures and monthly revenue, oldest first."""
        quarters, revenues = await self.daily_close_archive.financials(stock_id)

        return StockFinancials(quarters, revenues)

    async def load_stock_analysis(self, stock_id: str) -> StockAnalysis:
        """A stock's page: its revenue trend, earnings trend and valuation against its own history, read by fixed rules."""
        return await self.stock_analysis_lookup.execute(stock_id)

    async def load_stock_news(self, stock_id: str) -> list[Article] | None:
        """The stock page's kept articles, newest first, after a read of the sources. None for a stock that is not listed."""
        return await self.stock_news_lookup.execute(stock_id)

    async def refresh_article_store(self) -> None:
        """For the Web API's timer, the news of every stock a user holds or watches read into the article store and indexed."""
        for stock_id in await self.article_refresh_stocks.execute():
            await self.stock_news_lookup.execute(stock_id)
            await self.article_indexer.execute(stock_id)

    async def backfill_article_store(self) -> ArticleBackfill:
        """
        For `just backfill-articles`, keeps the open-data archive's announcements and TWSE news in the article store,
        then brings the vectors of every stock it keeps up to date.
        """
        kept, stock_ids = await self.article_store_backfill.execute()
        embedded = 0

        for stock_id in stock_ids:
            embedded += await self.article_indexer.execute(stock_id)

        return ArticleBackfill(kept, len(stock_ids), embedded)

    async def backfill_company_background(self, top: PositiveInt) -> CompanyBackfill:
        """
        For `just backfill-company-background`, reads the due main businesses and annual reports of the latest ranking's
        `top` best stocks. RankingUnavailable without a decision session.
        """
        history = await self.ranking_history_loader.execute()
        ranking = await self.latest_ranking.execute(history, top)
        stock_ids = [stock.stock_id for stock in ranking.stocks]
        businesses = await self.main_business_refresh.execute(stock_ids)
        reports = await self.annual_report_refresh.execute(stock_ids)

        return CompanyBackfill(len(stock_ids), businesses, reports)

    async def load_system_writing(self) -> list[str]:
        """For the Web API's timer, the stocks the site still writes a brief for by itself now; empty once the round is done."""
        return await self.system_writing_stocks.execute()

    async def refresh_world(self) -> None:
        """For the Web API's world timer, reads the world news feeds and indicators into what the site holds."""
        await self.world_refresh.execute()

    async def write_world_brief(self) -> None:
        """For the Web API's world timer, on the Pipeline of the site's own writing, writes the day's world brief once it is due."""
        context = await self.world_brief_context.execute()

        if context is None:
            return

        await self.world_brief.execute(MarketScope.WORLD.value, context)

    async def load_world(self) -> WorldOverview:
        """The world page and the home page's world block, as WorldLookup answers them."""
        return await self.world_lookup.execute()

    async def load_company(self, stock_id: str) -> CompanyFacts | None:
        """The stock page's facts about the company itself. None for a stock that is not listed."""
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.manual_stocks = await self.stock_lookup.execute([stock_id], status.stats)

        if not status.manual_stocks:
            return None

        analysis = await self.stock_analysis_lookup.execute(stock_id)
        profile, context = await self.company_background.execute(status.manual_stocks[0], analysis)
        cards = await self.company_card_lookup.execute(stock_id)

        return CompanyFacts(profile, [fact.source for fact in context.facts], cards.today, cards.previous)

    async def load_stock_brief(self, stock_id: str) -> HeldBriefs:
        """The stock page's AI brief of today in Taipei, its newest earlier one and how many more stocks may get one today."""
        return await self.stock_brief_lookup.execute(stock_id)

    async def write_stock_brief(self, stock_id: str) -> HeldBriefs | None:
        """
        Writes the stock's AI brief of today in Taipei, its company card first when due, for a signed-in viewer or the
        site's own timer, then answers what load_stock_brief answers. None for a stock that is not listed.
        """
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.manual_stocks = await self.stock_lookup.execute([stock_id], status.stats)

        if not status.manual_stocks:
            return None

        analysis = await self.stock_analysis_lookup.execute(stock_id)
        articles = await self.stock_news_lookup.execute(stock_id) or []
        await self.main_business_refresh.execute([stock_id])
        await self.annual_report_refresh.execute([stock_id])
        await self.article_indexer.execute(stock_id)
        _, card_context = await self.company_background.execute(status.manual_stocks[0], analysis)
        await self.company_card.execute(stock_id, card_context)
        cards = await self.company_card_lookup.execute(stock_id)
        history = await self.ranking_history_loader.execute()
        context = await self.stock_brief_context.execute(
            status.manual_stocks[0], analysis, articles, history, (cards.today, cards.previous)
        )

        await self.daily_stock_brief.execute(stock_id, context)

        return await self.stock_brief_lookup.execute(stock_id)

    async def count_archived_sessions(self) -> int:
        """The market overview's count of the sessions of stock closes the open-data archive holds."""
        return await self.daily_close_archive.session_count()

    async def load_market_breadth(self) -> MarketBreadth:
        """The market overview: the latest session's advancers and decliners in the exchange listing, overall and per industry."""
        return await self.market_breadth_loader.execute()

    async def load_index_history(self, index: MarketIndex, required_bars: int) -> list[Ohlcv]:
        """The market overview's trend: an index's daily history from the source the stock pages share."""
        return await self.index_history_loader.execute(index, required_bars)

    async def load_stock_history(self, stock_id: str, required_bars: int) -> PipelineStatus:
        """
        The stock page: one listed stock and its daily history, from the same cache the workflows read, its latest bar
        with the exchange's official change. A stock with stale history gets none, and status.stats says why.
        """
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.manual_stocks = await self.stock_lookup.execute([stock_id], status.stats)

        if not status.manual_stocks:
            return status

        await self.data_collector.execute(status.manual_stocks, required_bars, status.stats, official_change=True)

        return status

    async def evaluate_stock(self, stock_id: str) -> StockEvaluation:
        """
        The stock page's technical evaluation by the owner's active strategy, with each of its indicators at every bar
        of the window. Without a realtime quote, the latest price is the last daily close.
        """
        strategy = await self.strategy_loader.execute(Workflow.RESEARCH)
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.manual_stocks = await self.stock_lookup.execute([stock_id], status.stats)

        if not status.manual_stocks:
            return StockEvaluation(strategy, status)

        await self.data_collector.execute(status.manual_stocks, strategy.required_bars, status.stats)
        status.survivors = self.technical_filter.execute(status.manual_stocks, strategy, status.stats)
        status.indicator_readings = self.indicator_readings.execute(status.manual_stocks[0], strategy)

        return StockEvaluation(strategy, status)

    async def reply_to_chat(self, user_id: str, content: str) -> None:
        """Answers one chat message: a reset command clears the conversation, any other text gets the AI's reply."""
        replies = await self.chat_reply.execute(user_id, content)

        await self.dispatcher.execute(user_id, replies)

    async def load_technical_settings(self) -> TechnicalSettings:
        """The settings editor's read: the owner's saved strategies and selections, the initial ones on a first read."""
        return await self.technical_settings_repository.load()

    async def save_technical_settings(self, settings: TechnicalSettings) -> TechnicalSettings:
        """The settings editor's save. TechnicalSettingsConflictError, saving nothing, when `settings` carries an old revision."""
        return await self.technical_settings_repository.save(settings)

    async def load_settings_form(self) -> list[SettingField]:
        """The administrator's settings form. InvalidSettingsError for a file that does not parse."""
        return await self.settings_reader.execute()

    async def review_settings_form(self, changes: Sequence[SettingChange], host: str) -> list[SettingsEdit]:
        """
        The settings form's changes as an edit of each file. SettingsEditError for a change the form cannot write,
        InvalidSettingsError for texts the app would refuse, a lockout of the editor at `host` included.
        """
        return await self.settings_editor.execute(changes, host)

    async def confirm_settings_save(
        self, administrator: User, password: SecretStr | None, google_confirmation: GoogleConfirmation | None, client: str
    ) -> None:
        """
        The administrator's confirmation of a settings save by their password or a fresh Google authentication.
        PasswordRequired, PasswordRefused, SignInThrottled or GoogleConfirmationRequired otherwise.
        """
        await self.settings_confirmation.execute(administrator, password, google_confirmation, client)

    async def confirm_settings_with_google(
        self, flow: SignInFlow, confirmation: GoogleConfirmation, state: str | None, code: SecretStr | None, client: str
    ) -> None:
        """
        The browser's return from the fresh Google authentication of one settings save, which grants that save to the
        session that started it. GoogleSignInRefused or SignInThrottled, granting nothing.
        """
        email = await self.google_identity_check.execute(flow, state, code, client)
        await self.settings_reauthentication.execute(email, confirmation)

    async def confirm_editor_access(self, running: SignInOffer, saving: UserId | None) -> None:
        """
        InvalidSettingsError when the settings this runtime runs on would let no administrator into the editor, before a
        save by `saving` or a reload from disk (None) puts them in place.
        """
        candidate = await self.sign_in_options.execute()
        await self.editor_access.execute(candidate, running, saving)

    async def save_settings_file(self, edit: SettingsEdit, actor: UserId) -> SettingsEdit:
        """Writes an edit the app starts with, still at its base revision, with a backup and an audit entry naming `actor`."""
        return await self.settings_save.execute(edit, actor)

    async def load_sign_in_options(self) -> SignInOffer:
        """The sign-in screen and the CLI's start: is the first administrator still to be set up, and may anyone register?"""
        return await self.sign_in_options.execute()

    async def set_up_first_administrator(self, username: Username, email: EmailAddress, password: NewPassword) -> User:
        """First use, from the CLI or the Web: the administrator, who takes over the data of the single-owner version."""
        return await self.first_administrator_setup.execute(username, email, password)

    async def sign_in(self, identifier: str, password: SecretStr, client: str) -> User:
        """The CLI's sign-in: the user, inside the attempt limits. It raises SignInRefused or SignInThrottled."""
        return await self.sign_in_attempt.execute(identifier, password, client)

    async def load_user(self, user_id: UserId) -> User | None:
        """The user as saved now, for the CLI's check before each menu option. None when unknown or deactivated."""
        return await self.signed_in_user.execute(user_id)

    async def reset_password(self, identifier: str, password: NewPassword) -> User | None:
        """The operator's reset of a password on the machine: every session of the user ends. None for an unknown name."""
        user = await self.user_store.find_by_name(identifier)

        if user is None:
            return None

        return await self.user_change.execute(user.user_id, None, None, password)

    async def register(self, username: Username, email: EmailAddress, password: NewPassword, client: str) -> User:
        """Open registration: a new user with the role user. It raises RegistrationClosed or SignInThrottled."""
        return await self.user_registration.execute(username, email, password, client)

    async def sign_in_with_session(self, identifier: str, password: SecretStr, client: str) -> SignedIn:
        """The Web's sign-in: the same check as the CLI's, then a session for the browser's cookie."""
        user = await self.sign_in_attempt.execute(identifier, password, client)

        return SignedIn(user, await self.session_start.execute(user))

    async def start_google_sign_in(self, confirmation_id: str | None, session: SessionToken | None, client: str) -> GoogleRedirect:
        """
        Starts a sign-in with Google, or with `confirmation_id` the confirmation of one settings save from `session`,
        and answers the flow for the browser's cookie and Google's address. GoogleSignInRefused or SignInThrottled.
        """
        return await self.google_sign_in_start.execute(confirmation_id, session, client)

    async def sign_in_with_google(self, flow: SignInFlow | None, state: str | None, code: SecretStr | None, client: str) -> SignedIn:
        """
        The browser's return from Google: the email Google verified, its account as the settings admit it, created at
        the first sign-in, then a session for the browser's cookie. It raises GoogleSignInRefused or SignInThrottled.
        """
        email = await self.google_identity_check.execute(flow, state, code, client)
        user = await self.google_account.execute(email)

        return SignedIn(user, await self.session_start.execute(user))

    async def find_signed_in_user(self, token: SessionToken) -> User | None:
        """The user of an unexpired session while that user is active, else None, for every signed-in Web request."""
        return await self.user_store.session_user(token, self.market_clock.now())

    async def end_session(self, token: SessionToken) -> None:
        """The Web's sign-out. Ending a session that does not exist, or ended already, changes nothing."""
        await self.user_store.close_session(token)

    async def load_users(self) -> list[User]:
        """The administrator's list of users, oldest first."""
        return await self.user_store.users()

    async def change_user(
        self, user_id: UserId, role: Role | None, status: UserStatus | None, password: NewPassword | None
    ) -> User | None:
        """The administrator's change of a user's role, status or password. None when no such user exists."""
        return await self.user_change.execute(user_id, role, status, password)

    def load_ai_models(self, user: User) -> AiModels:
        """The AI models My settings shows: those the site offers, its default and the one the user's runs use."""
        return self.ai_model_lookup.execute(user)

    async def choose_ai_model(self, user: User, ai_model: AiProvider | None) -> AiModels:
        """
        My settings' save of the AI model for the user's next runs, None for the site's default, then what
        load_ai_models answers. AiModelNotOffered, saving nothing, for a model the site does not offer.
        """
        saved = await self.ai_model_choice.execute(user, ai_model)

        return self.ai_model_lookup.execute(saved)
