from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from pydantic import PositiveInt, SecretStr

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.system.user import GoogleConfirmation, SignInFlow, User, UserSession
from a_domain.model.trading.account import Account, BrokerageStatement, Position
from a_domain.model.trading.backtest import Backtest, BacktestInputs
from a_domain.model.trading.order import Order
from a_domain.model.valuation.scan import MarketValuation, ScanCriteria, ValuationScan
from a_domain.model.valuation.valuation import ReportSection, StockValuation, ValuationReport
from a_domain.ports.market.daily_close_archive import ArchivedMonth, ArchivedQuarter, ArchivedSession
from a_domain.ports.system.settings_files import SettingChange, SettingField, SettingsEdit
from a_domain.rules.fundamentals.stock_analysis import StockAnalysis
from a_domain.rules.market.breadth import MarketBreadth
from a_domain.rules.system.registration import SignInOffer
from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from a_domain.rules.trading.follow import FollowReturn, RankingHoldings
from a_domain.rules.trading.holdings import PortfolioAnalysis
from a_domain.rules.trading.ranking import Ranking
from a_domain.rules.trading.ranking_backtest import RankingBacktest
from a_domain.rules.trading.ranking_standing import RankingStanding
from a_domain.rules.watchlist.membership import WatchlistAddition
from a_domain.types.enums import (
    AiAnalysisFocus,
    AiProvider,
    FollowRefusal,
    HoldingSource,
    MarketIndex,
    MarketType,
    Role,
    UserStatus,
    WatchlistType,
    Workflow,
)
from a_domain.types.ids import BacktestId, RunId, SessionToken, UserId
from a_domain.types.values import EmailAddress, NewPassword, PositiveFiniteFloat, Username
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.admin.editor_access import EditorAccess
from b_application.use_cases.admin.settings_confirmation import SettingsConfirmation
from b_application.use_cases.admin.settings_editor import SettingsEditor
from b_application.use_cases.admin.settings_reader import SettingsReader
from b_application.use_cases.admin.settings_reauthentication import SettingsReauthentication
from b_application.use_cases.admin.settings_save import SettingsSave
from b_application.use_cases.backtest.backtest_lookup import BacktestLookup
from b_application.use_cases.backtest.backtest_options import BacktestOptions
from b_application.use_cases.backtest.backtest_removal import BacktestRemoval
from b_application.use_cases.backtest.backtest_replay import BacktestReplay
from b_application.use_cases.backtest.backtest_save import BacktestSave
from b_application.use_cases.backtest.backtest_scores import BacktestScores
from b_application.use_cases.backtest.saved_backtests import SavedBacktests
from b_application.use_cases.chat.chat_reply import ChatReply
from b_application.use_cases.chat.dispatcher import Dispatcher
from b_application.use_cases.collect.archive_warm_up import ArchiveWarmUp
from b_application.use_cases.collect.article_refresh_stocks import ArticleRefreshStocks
from b_application.use_cases.collect.article_store_backfill import ArticleStoreBackfill
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.daily_close_archiver import DailyCloseArchiver
from b_application.use_cases.collect.daily_history_backfill import DailyHistoryBackfill
from b_application.use_cases.collect.daily_history_refresh import DailyHistoryRefresh
from b_application.use_cases.collect.eps_history_backfill import EpsHistoryBackfill
from b_application.use_cases.collect.financials_lookup import FinancialsLookup
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
from b_application.use_cases.collect.revenue_history_backfill import RevenueHistoryBackfill
from b_application.use_cases.collect.stock_analysis_lookup import StockAnalysisLookup
from b_application.use_cases.collect.stock_brief_lookup import StockBriefLookup
from b_application.use_cases.collect.stock_lookup import StockLookup
from b_application.use_cases.collect.stock_news_lookup import StockNewsLookup
from b_application.use_cases.collect.stock_search import StockSearch
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.article_indexer import ArticleIndexer
from b_application.use_cases.process.indicator_readings import IndicatorReadings
from b_application.use_cases.process.sentiment_analyser import SentimentAnalyser
from b_application.use_cases.process.stock_brief_claim import StockBriefClaim
from b_application.use_cases.process.stock_brief_context import StockBriefContext
from b_application.use_cases.process.stock_brief_writer import StockBriefWriter
from b_application.use_cases.process.strategy_loader import StrategyLoader
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.process.technical_settings_editor import TechnicalSettingsEditor
from b_application.use_cases.ranking.latest_ranking import LatestRanking
from b_application.use_cases.ranking.ranking_history_loader import RankingHistoryLoader
from b_application.use_cases.ranking.ranking_replay import RankingReplay
from b_application.use_cases.ranking.ranking_standing import StockRankingStanding
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


@dataclass(slots=True)
class Pipeline:
    """
    Every operation the CLI, the Web API and the LINE webhook start. Each line of an operation names one step, the
    values it reads from the run's PipelineStatus and the field that keeps what it returns.

    A trading operation loads its technical strategy before its run record exists, so invalid settings stop a run that
    never started, and the run keeps that strategy until it ends. It then runs inside RunHistory.execute, so it has one
    run id and a saved run record; the Web API starts Full Cycle and specific-stock analysis under a run id it already
    returned to its caller. The valuation operations record no run and read only fields that cannot order.

    Buzz, Intraday, manual BUY and both follows send orders with the same four lines: each decision of the run that has no order yet,
    one at a time in decision order. OrderPreparation gates it and records its order right before the send, so OrderRule
    measures the quote's age at submission and BrokerAccessRule checks the broker the order would reach; OrderExecution
    sends it only when it is PENDING and records the broker's answer; OrderOutcome re-reads the account after a fill;
    and the order joins status.orders before the next decision is prepared, so a decision never gets a second order.
    Buzz and Intraday send twice: right after the stop-loss check, while those quotes are fresh, and at the end. Full
    Cycle, specific-stock analysis and valuation never send; a follow sends a finished Full Cycle's decisions, priced
    again, into the user's mock account, and a ranking follow what brings that account to the monthly ranking.

    Which broker the ordering steps hold (account_loader, order_preparation, order_execution, order_outcome) is the
    run's choice, fixed when dependencies.py builds this Pipeline for the run: the mock account unless an administrator
    chose a real broker. The mock_* steps always hold the user's mock account, and both follows use only them.

    A built-in strategy id, the CLI session's choice, makes a run use that built-in strategy instead of the saved one.

    Whose data an operation reads and writes is fixed when dependencies.py builds this Pipeline: every port that holds
    a user's data was built for one signed-in user, or for nobody (a signed-out Pipeline, whose such ports refuse with
    SignInRequired). No operation takes an owner, so none can be handed the wrong one.
    """

    strategy_loader: StrategyLoader
    technical_settings_editor: TechnicalSettingsEditor
    run_history: RunHistory
    account_loader: AccountLoader
    market_scanner: MarketScanner
    stock_lookup: StockLookup
    stock_search: StockSearch
    most_traded: MostTraded
    market_breadth_loader: MarketBreadthLoader
    index_history_loader: IndexHistoryLoader
    buzz_scanner: BuzzScanner
    intraday_candidates: IntradayCandidates
    data_collector: MarketDataCollector
    official_change_feed: OfficialChangeFeed
    daily_close_archiver: DailyCloseArchiver
    daily_history_refresh: DailyHistoryRefresh
    daily_history_backfill: DailyHistoryBackfill
    revenue_history_backfill: RevenueHistoryBackfill
    archive_warm_up: ArchiveWarmUp
    financials_lookup: FinancialsLookup
    eps_history_backfill: EpsHistoryBackfill
    stock_analysis_lookup: StockAnalysisLookup
    stock_news_lookup: StockNewsLookup
    article_indexer: ArticleIndexer
    article_refresh_stocks: ArticleRefreshStocks
    article_store_backfill: ArticleStoreBackfill
    stock_brief_lookup: StockBriefLookup
    stock_brief_context: StockBriefContext
    stock_brief_claim: StockBriefClaim
    stock_brief_writer: StockBriefWriter
    realtime_quote_feed: RealtimeQuoteFeed
    technical_filter: TechnicalFilter
    indicator_readings: IndicatorReadings
    news_feed: NewsFeed
    ai_analyser: AiAnalyser
    sentiment_analyser: SentimentAnalyser
    watch_stocks: WatchStocks
    unwatch_stocks: UnwatchStocks
    account_risk_check: AccountRiskCheck
    signals: Signals
    manual_signal: ManualSignal
    decision_memory: DecisionMemory
    order_preparation: OrderPreparation
    order_execution: OrderExecution
    order_outcome: OrderOutcome
    mock_account_loader: AccountLoader
    mock_order_preparation: OrderPreparation
    mock_order_execution: OrderExecution
    mock_order_outcome: OrderOutcome
    follow_candidates: FollowCandidates
    follow_signals: FollowSignals
    ranking_follow_candidates: RankingFollowCandidates
    ranking_follow_signals: RankingFollowSignals
    ranking_follow_return: RankingFollowReturn
    mock_account_history: AccountHistory
    trade_history: TradeHistory
    mock_account_reset: MockAccountReset
    brokerage_statement: BrokerageStatementReader
    held_positions: HeldPositions
    holdings_analysis: HoldingsAnalysis
    holding_entry: HoldingEntry
    holding_removal: HoldingRemoval
    reporting: Reporting
    run_reports: RunReports
    recent_runs: RecentRuns
    run_lookup: RunLookup
    active_watchlist: ActiveWatchlist
    account_history: AccountHistory
    backtest_options: BacktestOptions
    backtest_scores: BacktestScores
    backtest_replay: BacktestReplay
    backtest_save: BacktestSave
    saved_backtests: SavedBacktests
    backtest_lookup: BacktestLookup
    backtest_removal: BacktestRemoval
    ranking_history_loader: RankingHistoryLoader
    latest_ranking: LatestRanking
    ranking_standing: StockRankingStanding
    ranking_replay: RankingReplay
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
    user_lookup: UserLookup
    password_reset: PasswordReset
    user_registration: UserRegistration
    session_start: SessionStart
    session_user: SessionUser
    sign_out: SignOut
    user_directory: UserDirectory
    user_change: UserChange
    ai_model_lookup: AiModelLookup
    ai_model_choice: AiModelChoice

    async def run_full_cycle(self, run_id: RunId | None = None, built_in_strategy_id: str | None = None) -> PipelineStatus:
        """After-market analysis of the whole market. It records decisions priced from daily closes and never orders."""
        strategy = await self.strategy_loader.execute(Workflow.FULL_CYCLE, built_in_strategy_id)

        async with self.run_history.execute(Workflow.FULL_CYCLE, run_id) as stats:
            status = PipelineStatus(stats=stats)
            status.account, status.held_stocks = await self.account_loader.execute(status.stocks)
            status.universe_stocks = await self.market_scanner.execute(status.stats)
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
            await self.decision_memory.execute(status.signals, status.stocks, status.stats)
            await self.reporting.execute(status.signals, status.stats)

        return status

    async def run_buzz_scan(self, run_id: RunId | None = None, built_in_strategy_id: str | None = None) -> PipelineStatus:
        """
        Social momentum. Stop-loss SELLs go first, while their quotes are fresh; then the buzz stocks are analysed and
        decided. Every buzz stock is screened, so one without daily history gets a failing report. Sentiment is report
        only, so it runs after every trading step.
        """
        strategy = await self.strategy_loader.execute(Workflow.BUZZ_SCAN, built_in_strategy_id)

        async with self.run_history.execute(Workflow.BUZZ_SCAN, run_id) as stats:
            status = PipelineStatus(stats=stats)
            status.account, status.held_stocks = await self.account_loader.execute(status.stocks)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(status.held_stocks, status.stale_stock_ids, status.stats)
            status.equity, status.risk_blocked_stock_ids, status.signals = await self.account_risk_check.execute(
                status.account, status.held_stocks, status.stocks, status.stale_stock_ids, status.stats
            )
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.stats):
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
            await self.decision_memory.execute(status.signals, status.stocks, status.stats)
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.stats):
                    order = await self.order_execution.execute(order, status.stats)
                    status.account = await self.order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)
            status.sentiment_by_stock_id = await self.sentiment_analyser.execute(status.buzz_stocks, status.stats)
            await self.reporting.execute(status.signals, status.stats)

        return status

    async def run_intraday(self, run_id: RunId | None = None, built_in_strategy_id: str | None = None) -> PipelineStatus:
        """
        Revalidates the held and watched stocks. Stop-loss SELLs go first, while their quotes are fresh. A stock the run
        stopped out or could not quote gets no history, news or AI call, so a later fresh quote does not bring it back.
        Only stocks with daily history are screened, and every held stock screened gets its exit decided.
        """
        strategy = await self.strategy_loader.execute(Workflow.INTRADAY, built_in_strategy_id)

        async with self.run_history.execute(Workflow.INTRADAY, run_id) as stats:
            status = PipelineStatus(stats=stats)
            status.account, status.held_stocks = await self.account_loader.execute(status.stocks)
            status.candidates = await self.intraday_candidates.execute(status.held_stocks, status.stats)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(status.candidates, status.stale_stock_ids, status.stats)
            status.equity, status.risk_blocked_stock_ids, status.signals = await self.account_risk_check.execute(
                status.account, status.held_stocks, status.stocks, status.stale_stock_ids, status.stats
            )
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.stats):
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
            await self.decision_memory.execute(status.signals, status.stocks, status.stats)
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.stats):
                    order = await self.order_execution.execute(order, status.stats)
                    status.account = await self.order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)
            await self.reporting.execute(status.signals, status.stats)

        return status

    async def analyse_specific_stocks(
        self, stock_ids: list[str], run_id: RunId | None = None, built_in_strategy_id: str | None = None
    ) -> PipelineStatus:
        """
        Complete reports for the stocks the user asked for. Every stock goes through news and AI whatever its technical
        verdict, so the user can review it before a manual BUY, and a stock without daily history gets a failing report.
        Where the audience reads no news site, a stock with no archived article and no archived financials skips the AI
        call.
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
        The user's confirmed BUY of one analysed stock, as its own recorded run: `quantity` shares, or with None as many
        as sizing on the account's equity allows. It skips only the automatic buy threshold: the account, a fresh
        realtime quote, the decision record, the order gates (market open, price freshness, the broker the run chose
        and its limits) and the broker's own checks all still apply. The Web passes a stock a finished specific-stock
        run reported, whose saved price is a daily close the gates refuse, so only the realtime quote can price it.

        status.manual_buy_refusal says why no order was sent; otherwise status.orders holds the one order.
        """
        async with self.run_history.execute(Workflow.MANUAL_BUY, run_id) as stats:
            status = PipelineStatus(stats=stats, manual_stocks=[stock])
            status.account, status.held_stocks = await self.account_loader.execute(status.stocks)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(status.manual_stocks, status.stale_stock_ids, status.stats)
            status.signals, status.manual_buy_refusal = await self.manual_signal.execute(
                stock, quantity, status.account, status.stocks, status.stats
            )
            await self.decision_memory.execute(status.signals, status.stocks, status.stats)
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.stats):
                    order = await self.order_execution.execute(order, status.stats)
                    status.account = await self.order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)

        return status

    async def follow_run(self, followed_run_id: RunId, run_id: RunId | None = None) -> PipelineStatus:
        """
        The user's follow of one of their finished runs into their mock account, as its own recorded run that names the
        run it follows. Each decision still open to follow is priced again at the price this site orders at now: a
        fresh realtime quote in continuous trading where the site has them, else the official close of the last closed
        session while no session trades. A decision that gets no follow decision now stays open; one whose follow order
        fills is followed. A follow that may not start (FollowCandidates' refusal) records the refusal and sends nothing.
        Every step that reads the account, gates or sends an order holds the user's mock book (mock_account_loader,
        mock_order_preparation, mock_order_execution, mock_order_outcome), never the broker the run chose, so no follow
        reaches a real account whatever broker its Pipeline was built for.
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
                if order := await self.mock_order_preparation.execute(signal, status.orders, status.stats):
                    order = await self.mock_order_execution.execute(order, status.stats)
                    status.account = await self.mock_order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)

        return status

    async def load_follow(self, run_id: RunId) -> PipelineStatus:
        """
        The run page's follow panel, and the check before a follow starts: the run, its decisions still open to follow,
        every follow of them so far with its order, and why a follow may not start now. It records no run.
        """
        status = PipelineStatus.read_only(Workflow.FOLLOW)
        status.followed_run, status.followable_signals, status.follows, status.follow_refusal = await self.follow_candidates.execute(
            run_id
        )

        return status

    async def follow_ranking(self, run_id: RunId | None = None) -> PipelineStatus:
        """
        The user's follow of the monthly ranking's latest decision into their mock account, as its own recorded run: a
        SELL of each holding the ranking left, then a BUY of each ranked stock the account lacks at an equal weight of
        the account (RankingFollowRule), each priced as this site prices an order now, like a follow of a run; every
        holding is priced too, since the equal weight is a share of the account's value. A ranked
        stock the account already holds is left as it is, so a second follow of the same decision sends nothing but
        what the first could not fill. A follow that may not start (RankingFollowCandidates' refusal) records the
        refusal and sends nothing. Every step that reads the account, gates or sends an order holds the user's mock
        book (mock_account_loader, mock_order_preparation, mock_order_execution, mock_order_outcome), never the broker
        the run chose, so no ranking follow reaches a real account whatever broker its Pipeline was built for.
        RankingUnavailable while the history holds no decision session.
        """
        async with self.run_history.execute(Workflow.RANKING_FOLLOW, run_id) as stats:
            status = PipelineStatus(stats=stats)
            history = await self.ranking_history_loader.execute()
            ranking = await self.latest_ranking.execute(history)
            holdings, status.follow_refusal = await self.ranking_follow_candidates.execute(ranking)

            if status.follow_refusal is not None:
                return status

            status.manual_stocks = await self.stock_lookup.execute(holdings.lacking, status.stats)
            status.account, status.held_stocks = await self.mock_account_loader.execute(status.stocks)
            traded = [*status.held_stocks, *status.manual_stocks]
            await self.data_collector.execute(traded, 1, status.stats)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(traded, status.stale_stock_ids, status.stats)
            status.signals = await self.ranking_follow_signals.execute(ranking, status.stocks, status.account, status.stats)
            for signal in status.signals:
                if order := await self.mock_order_preparation.execute(signal, status.orders, status.stats):
                    order = await self.mock_order_execution.execute(order, status.stats)
                    status.account = await self.mock_order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)

        return status

    async def load_ranking_follow(self) -> tuple[RankingHoldings, FollowRefusal | None]:
        """
        The ranking page's block on the mock account, and the check before a ranking follow starts: which of the
        ranking's stocks the user's mock account holds and lacks and which holdings the ranking left, and why a follow
        may not start now. It records no run and never orders. RankingUnavailable while the history holds no decision
        session.
        """
        history = await self.ranking_history_loader.execute()
        ranking = await self.latest_ranking.execute(history)

        return await self.ranking_follow_candidates.execute(ranking)

    async def load_ranking_follow_return(self) -> FollowReturn | None:
        """
        The ranking page's block on the mock account: what the account made since it first followed the ranking,
        against the ranking's benchmark over the same sessions; None while it never did. It reads the mock account's
        own history (mock_account_history), records no run and never orders. RankingUnavailable while the history
        holds no session.
        """
        history = await self.ranking_history_loader.execute()
        account, _, curve, _ = await self.mock_account_history.execute(None)

        return await self.ranking_follow_return.execute(history, account, curve)

    async def load_trades(self, limit: int, offset: int) -> list[tuple[Order, SystemStats]]:
        """The account page's trades since the mock account opened, newest first, each with the run whose decision it carried out."""
        return await self.trade_history.execute(limit, offset)

    async def reset_mock_account(self, initial_cash: PositiveFiniteFloat) -> Account:
        """My settings' reset: the user's mock account opens again with `initial_cash` and no positions. It records no run."""
        return await self.mock_account_reset.execute(initial_cash)

    async def load_brokerage_statement(self) -> BrokerageStatement | None:
        """
        The SinoPac account page: the real broker's account as the broker reports it now. None while the site has no
        real broker for the user or its login is down. It never orders and records no run.
        """
        return await self.brokerage_statement.execute()

    async def load_holdings(self, sources: frozenset[HoldingSource]) -> PortfolioAnalysis:
        """
        The My holdings page: what the user holds under each of `sources` it could read, as one portfolio at the last
        closes held, each stock with its standing in the monthly ranking, the one load_ranking_standing answers on the
        stock page. It reads held data and the accounts, asks no AI, records no run and never orders.
        RankingUnavailable while the history holds no decision session.
        """
        held = await self.held_positions.execute(sources)
        history = await self.ranking_history_loader.execute()
        stock_ids = sorted({position.stock_id for positions in held.values() for position in positions})
        standings = {stock_id: await self.ranking_standing.execute(history, stock_id) for stock_id in stock_ids}

        return await self.holdings_analysis.execute(held, history, standings)

    async def enter_holding(
        self, stock_id: str, quantity: PositiveInt, average_cost: PositiveFiniteFloat, opened_on: date | None
    ) -> Position | None:
        """
        The My holdings page's entry: the user's hand-entered holding of a listed stock, replacing an earlier one of the
        same stock. None, and nothing kept, when the listing has no such stock. It orders nothing.
        """
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.manual_stocks = await self.stock_lookup.execute([stock_id], status.stats)

        if not status.manual_stocks:
            return None

        return await self.holding_entry.execute(status.manual_stocks[0], quantity, average_cost, opened_on)

    async def remove_holding(self, stock_id: str) -> bool:
        """The My holdings page's removal of a hand-entered holding. False when the stock had none."""
        return await self.holding_removal.execute(stock_id)

    async def watch_manually(self, stock_ids: list[str]) -> tuple[list[Stock], WatchlistAddition | None]:
        """
        Menu 4 and the watchlist endpoint: the listed stocks join the MANUAL watchlist, which never expires. When the
        listing lacks one of the ids nothing is added: the addition is None, and the stocks found tell which ids.
        """
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.manual_stocks = await self.stock_lookup.execute(stock_ids, status.stats)

        if len(status.manual_stocks) < len(set(stock_ids)):
            return status.manual_stocks, None

        return status.manual_stocks, await self.watch_stocks.execute(status.manual_stocks, WatchlistType.MANUAL)

    async def unwatch_manually(self, stock_ids: list[str]) -> list[str]:
        """The watchlist endpoint's removal: only MANUAL entries go; it returns the stocks that had one."""
        return await self.unwatch_stocks.execute(stock_ids)

    async def load_watchlist(self) -> PipelineStatus:
        """
        The watchlist endpoint: every active entry, one per stock and watchlist type, and the listing that names the
        watched stocks; a listing outage leaves them unnamed rather than failing the page.
        """
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.watchlist = await self.active_watchlist.execute()
        status.universe_stocks = await self.market_scanner.execute(status.stats)

        return status

    async def load_runs(self, limit: int, offset: int) -> list[SystemStats]:
        """The runs endpoint: `limit` recorded runs, newest first, after the `offset` newest, whichever entry point started them."""
        return await self.recent_runs.execute(limit, offset)

    async def load_run(self, run_id: RunId) -> PipelineStatus | None:
        """
        One recorded run as its status: the record, the specific-stock reports as manual_stocks, the decisions and the
        orders. None when the journal holds no such run.
        """
        recorded = await self.run_lookup.execute(run_id)

        if recorded is None:
            return None

        stats, reports, signals, orders = recorded

        return PipelineStatus(stats=stats, manual_stocks=reports, signals=signals, orders=orders)

    async def load_account_history(self, as_of: date | None) -> PipelineStatus:
        """
        Menu 7 and the account endpoint: the account now, its equity curve and the account as of a date. It records no
        run and never orders.
        """
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.account, status.held_stocks, status.equity_curve, status.account_as_of = await self.account_history.execute(as_of)

        return status

    async def load_backtest_options(self, built_in_strategy_id: str | None = None) -> tuple[TechnicalStrategy, BacktestInputs | None]:
        """
        The backtest page: the strategy a backtest would replay, the owner's active one or a built-in one, and the
        inputs of the longest backtest the held daily history allows at the live settings; None while it allows none.
        It loads no bar and records no run.
        """
        strategy = await self.strategy_loader.execute(Workflow.RESEARCH, built_in_strategy_id)

        return strategy, await self.backtest_options.execute(strategy)

    async def run_backtest(self, inputs: BacktestInputs, built_in_strategy_id: str | None = None) -> Backtest:
        """
        What the strategy would have done over the sessions `inputs` name: its scores of every listed stock on every
        session, the live trading rules replayed on those scores alone, and the result saved for the user. It reads
        only daily history the site already holds, asks no AI, touches no account, watchlist or journal, records no
        run and never orders. BacktestPeriodUnavailable for a period the held history cannot replay.
        """
        strategy = await self.strategy_loader.execute(Workflow.RESEARCH, built_in_strategy_id)
        bars, scores = await self.backtest_scores.execute(strategy, inputs)
        backtest = await self.backtest_replay.execute(strategy, inputs, bars, scores)
        await self.backtest_save.execute(backtest)

        return backtest

    async def load_ranking(self) -> Ranking:
        """
        The monthly stock ranking by revenue acceleration and nearness to the high at the latest decision session the held
        daily history holds: its stocks with their two factors, two ranks and score, the session and the revenue month it
        read. It reads only the held history and the archived revenue, asks no AI, records no run and never orders.
        RankingUnavailable while the history holds no decision session.
        """
        history = await self.ranking_history_loader.execute()

        return await self.latest_ranking.execute(history)

    async def load_ranking_standing(self, stock_id: str) -> RankingStanding:
        """
        The stock page: where the stock stands in the monthly ranking at the latest decision session the held history
        holds, its place among the scored stocks, its score from 0 to 100 and its two factors, or why the ranking
        leaves it out. It reads what load_ranking reads, from the same held history, asks no AI, records no run and
        never orders. RankingUnavailable while the history holds no decision session.
        """
        history = await self.ranking_history_loader.execute()

        return await self.ranking_standing.execute(history, stock_id)

    async def run_ranking_backtest(self, first: date, last: date) -> RankingBacktest:
        """
        The monthly ranking replayed over the decision sessions from `first` to `last` against its benchmark held over
        the same sessions, at the live fee and tax: its value at every session, each decision's ranking and holdings.
        It reads only the held history and the archived revenue, saves nothing, asks no AI and never orders.
        BacktestPeriodUnavailable for a period without a decision session.
        """
        history = await self.ranking_history_loader.execute()

        return await self.ranking_replay.execute(history, first, last)

    async def load_backtests(self) -> list[Backtest]:
        """The user's saved backtests, newest first."""
        return await self.saved_backtests.execute()

    async def load_backtest(self, backtest_id: BacktestId) -> Backtest | None:
        """One of the user's saved backtests; None when the user has none of that id."""
        return await self.backtest_lookup.execute(backtest_id)

    async def delete_backtest(self, backtest_id: BacktestId) -> bool:
        """Deletes one of the user's saved backtests, and answers whether the user had one of that id."""
        return await self.backtest_removal.execute(backtest_id)

    async def load_market_valuation(self) -> MarketValuation:
        """
        Every listed and OTC stock with its official close, TTM EPS and industry: bulk sources, a few requests. The
        steps' errors so far, such as a MOPS quarter that failed, become the valuation's source warnings.
        """
        status = PipelineStatus.read_only(Workflow.VALUATION)
        status.universe_stocks = await self.market_scanner.execute(status.stats)
        await self.fundamentals_feed.execute(status.universe_stocks, status.stats)

        return await self.market_valuation_loader.execute(status.universe_stocks, status.stats)

    def appraise_valuations(
        self, valuations: Sequence[StockValuation], target_pe: PositiveFiniteFloat | None
    ) -> list[ValuationReport]:
        """Menu 5's chosen stocks, each valued at the user's target P/E, in the order chosen."""
        return self.valuation_appraiser.execute(valuations, target_pe)

    def screen_valuation(self, market: MarketValuation, criteria: ScanCriteria) -> ValuationScan:
        """The undervalued scan's valuation step at the user's criteria. It offers at most max_scan_explanations stocks to the AI."""
        return self.valuation_screener.execute(market, criteria)

    async def confirm_valuation_technical(self, scan: ValuationScan, built_in_strategy_id: str | None = None) -> ValuationScan:
        """The undervalued scan's second step: the active technical strategy, applied exactly as the trading workflows apply it."""
        strategy = await self.strategy_loader.execute(Workflow.VALUATION, built_in_strategy_id)
        status = PipelineStatus.read_only(Workflow.VALUATION)
        status.technical_candidates = await self.data_collector.execute(scan.survivor_stocks, strategy.required_bars, status.stats)
        status.survivors = self.technical_filter.execute(status.technical_candidates, strategy, status.stats)

        return scan.after_technical_step(strategy.strategy_id)

    async def explain_valuation(self, report: ValuationReport) -> tuple[ReportSection, ...]:
        """The domain computed every number; the AI explains them with the stock's news."""
        status = PipelineStatus.read_only(Workflow.VALUATION)
        await self.news_feed.execute([report.stock], status.stats)

        return await self.valuation_explainer.execute(report)

    async def search_stocks(self, query: str) -> list[Stock]:
        """The stock search: listed stocks by code or name, with their latest official close. It records no run."""
        return await self.stock_search.execute(query)

    async def load_most_traded(self) -> list[Stock]:
        """The market overview: the latest session's most traded stocks in the exchange listing."""
        return await self.most_traded.execute()

    async def archive_daily_closes(self) -> tuple[list[ArchivedSession], list[ArchivedQuarter], list[ArchivedMonth]]:
        """
        The Web API's timer: the official closes, material information, EPS statistics, valuation ratios, balance
        sheets, income statements, monthly revenue and TWSE news the TWSE and TPEX OpenAPI serve now, saved into the
        archive, then every date, quarter and month it holds. No run record. `just archive-closes` runs the same step
        without a Pipeline, which would need every adapter (open_archiver).
        """
        return await self.daily_close_archiver.execute()

    async def refresh_daily_history(self) -> tuple[date, date] | None:
        """
        The Web API's timer on a personal site: the exchanges' daily reports of every session the history cache lacks
        over the stock page's longest chart, and the window's first and last session; None where the daily history is
        the open-data archive's. No run record.
        """
        return await self.daily_history_refresh.execute()

    async def backfill_history(
        self, first: date
    ) -> tuple[
        tuple[list[date], list[date], list[tuple[MarketType, date, date]]] | None, tuple[int, int] | None, tuple[int, int] | None
    ]:
        """
        `just backfill-history`: what a ranking backtest and the stock pages' trends read, back to `first` on a personal
        site. Every market's monthly revenue from MOPS's summary of each month into the open-data archive, the months
        read of those due; every market's MOPS page of year-to-date EPS of each quarter, the quarters held of those due;
        then TWSE's ex-right references and each exchange's daily history into the history cache, the sessions it
        holds, those it still lacks and the index ranges it could not read. Each part saves what it fetched as it comes,
        so a rerun after a failure or a timeout fetches only what is still missing. A part the site does not read is
        None: a public site reads none. No run record, no broker, no AI.
        """
        revenue = await self.revenue_history_backfill.execute(first)
        eps = await self.eps_history_backfill.execute(first)
        history = await self.daily_history_backfill.execute(first)

        return history, revenue, eps

    async def load_financials(self, stock_id: str) -> tuple[list[QuarterFinancials], list[MonthlyRevenue]]:
        """A stock's page: its archived quarters' figures and monthly revenue, oldest first. No run record."""
        return await self.financials_lookup.execute(stock_id)

    async def load_stock_analysis(self, stock_id: str) -> StockAnalysis:
        """
        A stock's page: its revenue trend, earnings trend and valuation against its own history, read from held data
        alone, with their reading in sentences by fixed rules. No fetch, no AI call, no run record.
        """
        return await self.stock_analysis_lookup.execute(stock_id)

    async def load_stock_news(self, stock_id: str) -> list[Article] | None:
        """
        A stock's page: what the article store keeps of the stock, newest first, once it holds what there is to read now,
        the archived material information and TWSE news of the stock and, where the site may read them, the news sites'
        articles and the board's posts as held within their freshness window. None for a stock that is not listed. No
        AI call, no embedding, no run record.
        """
        return await self.stock_news_lookup.execute(stock_id)

    async def refresh_article_store(self) -> tuple[int, int]:
        """
        The Web API's timer: the news of every stock a user holds or watches read into the article store as a stock
        page reads it, one stock after another at the stock feed's pace,
        each stock's vectors brought up to date after it. It answers how many stocks it read and how many articles it
        embedded. No AI call, no account, no run record, and it never orders.
        """
        stock_ids = await self.article_refresh_stocks.execute()
        embedded = 0

        for stock_id in stock_ids:
            await self.stock_news_lookup.execute(stock_id)
            embedded += await self.article_indexer.execute(stock_id)

        return len(stock_ids), embedded

    async def backfill_article_store(self) -> tuple[int, int, int]:
        """
        `just backfill-articles`: the announcements and TWSE news the open-data archive holds kept in the article store,
        then the vectors of every stock the store keeps brought up to date, which also fills an index that was lost. It
        answers the articles it added or replaced, the stocks the store keeps and the articles it embedded. Run again,
        it adds and embeds nothing. It reaches no news site, asks no AI, records no run and never orders.
        """
        kept, stock_ids = await self.article_store_backfill.execute()
        embedded = 0

        for stock_id in stock_ids:
            embedded += await self.article_indexer.execute(stock_id)

        return kept, len(stock_ids), embedded

    async def load_stock_brief(self, stock_id: str) -> tuple[StockBrief | None, StockBrief | None, int]:
        """
        A stock's page: the AI brief the site holds of the stock today in Taipei, its newest written brief of an earlier
        day, and how many more stocks may get a new brief today. No AI call, no fetch, no run record.
        """
        return await self.stock_brief_lookup.execute(stock_id)

    async def write_stock_brief(self, stock_id: str) -> tuple[StockBrief | None, StockBrief | None, int] | None:
        """
        A signed-in viewer asks for a stock's AI brief of today in Taipei: what the company is and how the held facts of
        a recent window relate to the stock's move, from the stock's held analysis, news and ranking standing alone. The
        news is what its searches find in the article store, whose vectors of the stock are brought up to date first.
        The site writes one per stock and day, so only the request that claims it calls the AI, once, on the user's
        counted provider; every other request answers what is held. Then what load_stock_brief answers. None for a
        stock that is not listed. It records no run, reads no account and never orders.
        """
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.manual_stocks = await self.stock_lookup.execute([stock_id], status.stats)

        if not status.manual_stocks:
            return None

        analysis = await self.stock_analysis_lookup.execute(stock_id)
        articles = await self.stock_news_lookup.execute(stock_id) or []
        await self.article_indexer.execute(stock_id)
        history = await self.ranking_history_loader.execute()
        context = await self.stock_brief_context.execute(status.manual_stocks[0], analysis, articles, history)
        brief = await self.stock_brief_claim.execute(context)

        if brief is not None:
            await self.stock_brief_writer.execute(brief, context)

        return await self.stock_brief_lookup.execute(stock_id)

    async def load_archive_warm_up(self) -> tuple[int, int]:
        """
        The market overview's open-data archive: the sessions of stock closes it holds, and the daily bars the built-in
        strategies need, which an open-data deployment's runs wait for. No run record.
        """
        return await self.archive_warm_up.execute()

    async def load_market_breadth(self) -> MarketBreadth:
        """The market overview: the latest session's advancers and decliners in the exchange listing, overall and per industry."""
        return await self.market_breadth_loader.execute()

    async def load_index_history(self, index: MarketIndex, required_bars: int) -> list[Ohlcv]:
        """The market overview's trend: an index's daily history from the source the stock pages share. No run record."""
        return await self.index_history_loader.execute(index, required_bars)

    async def load_stock_history(self, stock_id: str, required_bars: int) -> PipelineStatus:
        """
        The stock page: one listed stock and its daily history, from the same cache the workflows read. No realtime
        quote, no AI call, no run record. A stock with stale history gets none, and status.stats says why.
        """
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.manual_stocks = await self.stock_lookup.execute([stock_id], status.stats)

        if not status.manual_stocks:
            return status

        await self.data_collector.execute(status.manual_stocks, required_bars, status.stats)
        status.manual_stocks = await self.official_change_feed.execute(status.manual_stocks)

        return status

    async def evaluate_stock(self, stock_id: str) -> tuple[TechnicalStrategy, PipelineStatus]:
        """
        The stock page's technical evaluation: the owner's active strategy over the history window a run loads for
        it, and each of its indicators at every bar of that window. Without a realtime quote, the latest price is the
        last daily close. No AI call, no run record, no order.
        """
        strategy = await self.strategy_loader.execute(Workflow.RESEARCH)
        status = PipelineStatus.read_only(Workflow.RESEARCH)
        status.manual_stocks = await self.stock_lookup.execute([stock_id], status.stats)

        if not status.manual_stocks:
            return strategy, status

        await self.data_collector.execute(status.manual_stocks, strategy.required_bars, status.stats)
        status.survivors = self.technical_filter.execute(status.manual_stocks, strategy, status.stats)
        status.indicator_readings = self.indicator_readings.execute(status.manual_stocks[0], strategy)

        return strategy, status

    async def reply_to_chat(self, user_id: str, content: str) -> None:
        """Answers one chat message: a reset command clears the conversation, any other text gets the AI's reply."""
        replies = await self.chat_reply.execute(user_id, content)

        await self.dispatcher.execute(user_id, replies)

    async def load_technical_settings(self) -> TechnicalSettings:
        """The settings editor's read: the owner's saved strategies and selections, the initial ones on a first read."""
        return await self.technical_settings_editor.execute()

    async def save_technical_settings(self, settings: TechnicalSettings) -> TechnicalSettings:
        """
        The settings editor's save. It raises TechnicalSettingsConflictError, saving nothing, when another save came
        after the revision `settings` carries. A run already loaded its strategy, so the next run uses these settings.
        """
        return await self.technical_settings_editor.execute(settings)

    async def load_settings_form(self) -> list[SettingField]:
        """
        The administrator's settings form: every setting and AI prompt, with the value the files on disk set, else its
        default. InvalidSettingsError at the parser's mark for a file that does not parse.
        """
        return await self.settings_reader.execute()

    async def review_settings_form(self, changes: Sequence[SettingChange], host: str) -> list[SettingsEdit]:
        """
        The settings form's changes, reviewed: SettingsEditError for a change the form cannot write, InvalidSettingsError
        with the problems of new texts the app would refuse, a lockout of the editor reached at `host` included. The
        edit of each file the changes change; nothing is written.
        """
        return await self.settings_editor.execute(changes, host)

    async def confirm_settings_save(
        self, administrator: User, password: SecretStr | None, google_confirmation: GoogleConfirmation | None, client: str
    ) -> None:
        """
        The administrator confirms a save of the settings: PasswordRequired, PasswordRefused or SignInThrottled without
        their own password inside its attempt limit, or GoogleConfirmationRequired for an administrator without a
        password and without the fresh Google authentication `google_confirmation` names, started from the session
        that saves, which is used up here.
        """
        await self.settings_confirmation.execute(administrator, password, google_confirmation, client)

    async def confirm_settings_with_google(
        self, flow: SignInFlow, confirmation: GoogleConfirmation, state: str | None, code: SecretStr | None, client: str
    ) -> None:
        """
        The browser's return from the fresh Google authentication an administrator without a password made for one
        settings save: the save `confirmation` names is granted to the session that started it, when Google
        authenticated that session's administrator just now.
        It raises GoogleSignInRefused or SignInThrottled, granting nothing.
        """
        email = await self.google_identity_check.execute(flow, state, code, client)
        await self.settings_reauthentication.execute(email, confirmation)

    async def confirm_editor_access(self, running: SignInOffer, saving: UserId | None) -> None:
        """
        The settings this Pipeline's runtime runs on, before a save (`saving`, the administrator) or a reload from disk
        (None) puts them in place, compared with the running settings' sign-in offer: InvalidSettingsError when no
        administrator could sign in to the editor.
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
        return await self.user_lookup.execute(user_id)

    async def reset_password(self, identifier: str, password: NewPassword) -> User | None:
        """The operator's reset of a password on the machine: every session of the user ends. None for an unknown name."""
        return await self.password_reset.execute(identifier, password)

    async def register(self, username: Username, email: EmailAddress, password: NewPassword, client: str) -> User:
        """Open registration: a new user with the role user. It raises RegistrationClosed or SignInThrottled."""
        return await self.user_registration.execute(username, email, password, client)

    async def sign_in_with_session(self, identifier: str, password: SecretStr, client: str) -> tuple[User, UserSession]:
        """The Web's sign-in: the same check as the CLI's, then a session for the browser's cookie."""
        user = await self.sign_in_attempt.execute(identifier, password, client)

        return user, await self.session_start.execute(user)

    async def start_google_sign_in(
        self, confirmation_id: str | None, session: SessionToken | None, client: str
    ) -> tuple[SignInFlow, str]:
        """
        The start of a sign-in with Google, or with a `confirmation_id` of the fresh authentication that confirms one
        settings save from `session`, the caller's: the flow for the browser's cookie and Google's address for it. It
        raises GoogleSignInRefused where the site offers none or a confirmation comes without an administrator's
        session, or SignInThrottled.
        """
        return await self.google_sign_in_start.execute(confirmation_id, session, client)

    async def sign_in_with_google(
        self, flow: SignInFlow | None, state: str | None, code: SecretStr | None, client: str
    ) -> tuple[User, UserSession]:
        """
        The browser's return from Google: the email Google verified, its account as the settings admit it, created at
        the first sign-in, then a session for the browser's cookie. It raises GoogleSignInRefused or SignInThrottled.
        """
        email = await self.google_identity_check.execute(flow, state, code, client)
        user = await self.google_account.execute(email)

        return user, await self.session_start.execute(user)

    async def find_signed_in_user(self, token: SessionToken) -> User | None:
        """Every signed-in Web request, before dependencies.py builds that user's Pipeline: the session's user, now."""
        return await self.session_user.execute(token)

    async def end_session(self, token: SessionToken) -> None:
        """The Web's sign-out."""
        await self.sign_out.execute(token)

    async def load_users(self) -> list[User]:
        """The administrator's list of users."""
        return await self.user_directory.execute()

    async def change_user(
        self, user_id: UserId, role: Role | None, status: UserStatus | None, password: NewPassword | None
    ) -> User | None:
        """The administrator's change of a user's role, status or password. None when no such user exists."""
        return await self.user_change.execute(user_id, role, status, password)

    def load_ai_models(self, user: User) -> tuple[dict[AiProvider, str], AiProvider, AiProvider]:
        """
        My settings: each AI model the site offers with its model id, the site's default, and the model the user's runs
        use, their choice while the site offers it, else the default.
        """
        return self.ai_model_lookup.execute(user)

    async def choose_ai_model(self, user: User, ai_model: AiProvider | None) -> tuple[dict[AiProvider, str], AiProvider, AiProvider]:
        """
        My settings' save of the AI model for the user's next runs, one the site offers or None for the site's default,
        then what load_ai_models answers. It raises AiModelNotOffered, saving nothing, for a model the site does not offer.
        """
        saved = await self.ai_model_choice.execute(user, ai_model)

        return self.ai_model_lookup.execute(saved)
