from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from pydantic import SecretStr

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.system.user import User, UserSession
from a_domain.model.valuation.scan import MarketValuation, ScanCriteria, ValuationScan
from a_domain.model.valuation.valuation import ReportSection, StockValuation, ValuationReport
from a_domain.ports.system.settings_files import (
    SettingChange,
    SettingsAuditEntry,
    SettingsBackup,
    SettingsDocument,
    SettingsEdit,
    SettingsForm,
)
from a_domain.rules.market.breadth import MarketBreadth
from a_domain.rules.system.registration import SignInOffer
from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from a_domain.rules.watchlist.membership import WatchlistAddition
from a_domain.types.enums import AiAnalysisFocus, AiProvider, MarketIndex, Role, SettingsFile, UserStatus, WatchlistType, Workflow
from a_domain.types.ids import RunId, SessionToken, UserId
from a_domain.types.values import EmailAddress, NewPassword, PositiveFiniteFloat, Username
from b_application.schemas.pipeline_status import PipelineStatus
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


@dataclass(slots=True)
class Pipeline:
    """
    Every operation the CLI, the Web API and the LINE webhook start. Each line of an operation names one step, the
    values it reads from the run's PipelineStatus and the field that keeps what it returns.

    A trading operation loads its technical strategy before its run record exists, so invalid settings stop a run that
    never started, and the run keeps that strategy until it ends. It then runs inside RunHistory.execute, so it has one
    run id and a saved run record; the Web API starts Full Cycle and specific-stock analysis under a run id it already
    returned to its caller. The valuation operations record no run and read only fields that cannot order.

    Buzz, Intraday and manual BUY send orders with the same four lines: each decision of the run that has no order yet,
    one at a time in decision order. OrderPreparation gates it and records its order right before the send, so OrderRule
    measures the quote's age at submission; OrderExecution sends it only when it is PENDING and records the broker's
    answer; OrderOutcome re-reads the account after a fill; and the order joins status.orders before the next decision
    is prepared, so a decision never gets a second order. Buzz and Intraday send twice: right after the stop-loss check,
    while those quotes are fresh, and at the end. Full Cycle, specific-stock analysis and valuation never send.

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
    reporting: Reporting
    run_reports: RunReports
    recent_runs: RecentRuns
    run_lookup: RunLookup
    active_watchlist: ActiveWatchlist
    account_history: AccountHistory
    fundamentals_feed: FundamentalsFeed
    market_valuation_loader: MarketValuationLoader
    valuation_appraiser: ValuationAppraiser
    valuation_screener: ValuationScreener
    valuation_explainer: ValuationExplainer
    chat_reply: ChatReply
    dispatcher: Dispatcher
    settings_reader: SettingsReader
    settings_backups: SettingsBackups
    settings_audit: SettingsAudit
    settings_editor: SettingsEditor
    settings_form_editor: SettingsFormEditor
    settings_confirmation: SettingsConfirmation
    settings_save: SettingsSave
    editor_access: EditorAccess
    sign_in_options: SignInOptions
    first_administrator_setup: FirstAdministratorSetup
    sign_in_attempt: SignInAttempt
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

    async def buy_manually(self, stock: Stock) -> PipelineStatus:
        """
        The user's confirmed BUY of one analysed stock, as its own recorded run. It skips only the automatic buy
        threshold: the account, the realtime quote, sizing on the account's equity, the decision record, the order gates
        (order mode, market open, price freshness) and the broker's own checks all still apply.

        status.manual_buy_refusal says why no order was sent; otherwise status.orders holds the one order.
        """
        async with self.run_history.execute(Workflow.MANUAL_BUY) as stats:
            status = PipelineStatus(stats=stats, manual_stocks=[stock])
            status.account, status.held_stocks = await self.account_loader.execute(status.stocks)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(status.manual_stocks, status.stale_stock_ids, status.stats)
            status.signals, status.manual_buy_refusal = await self.manual_signal.execute(
                stock, status.account, status.stocks, status.stats
            )
            await self.decision_memory.execute(status.signals, status.stocks, status.stats)
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.stats):
                    order = await self.order_execution.execute(order, status.stats)
                    status.account = await self.order_outcome.execute(order, status.account, status.stocks, status.stats)
                    status.orders.append(order)

        return status

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

    async def load_market_breadth(self) -> MarketBreadth:
        """The market overview: the latest session's advancers and decliners in the exchange listing, overall and per industry."""
        return await self.market_breadth_loader.execute()

    async def load_index_history(self, index: MarketIndex, required_bars: int) -> list[Ohlcv]:
        """The market overview's trend: an index's daily history from the cache the stock pages share. No run record."""
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

    async def read_settings_file(self, file: SettingsFile) -> SettingsDocument:
        """One settings file as it is on disk."""
        return await self.settings_reader.execute(file)

    async def list_settings_backups(self, file: SettingsFile) -> list[SettingsBackup]:
        """The kept backups of one settings file, newest first."""
        return await self.settings_backups.execute(file)

    async def load_settings_audit(self, limit: int) -> list[tuple[SettingsAuditEntry, User | None]]:
        """The latest saves and restores, newest first, each with the administrator who made it."""
        return await self.settings_audit.execute(limit)

    async def preview_settings_file(
        self, file: SettingsFile, expected_revision: str, host: str, text: str | None = None, backup_id: str | None = None
    ) -> SettingsEdit:
        """
        The administrator's whole new text, or a kept backup to put back, against the file on disk and the settings this
        Pipeline's runtime runs on: what it changes, what applies only at a restart, and its problems, a lockout of the
        editor reached at `host` included. Nothing is written.
        """
        return await self.settings_editor.execute(file, expected_revision, host, text, backup_id)

    def edit_settings_form(self, text: str, changes: Sequence[SettingChange]) -> SettingsForm:
        """
        A text of appsetting.yaml as the settings form shows it, with the form's changes written into it in place.
        Nothing is written: the page checks and saves the text it answers like any text the administrator types.
        """
        return self.settings_form_editor.execute(text, changes)

    async def review_settings_save(
        self,
        administrator: User,
        file: SettingsFile,
        expected_revision: str,
        host: str,
        password: SecretStr | None,
        client: str,
        text: str | None = None,
        backup_id: str | None = None,
    ) -> SettingsEdit:
        """
        A save or a restore, reviewed as its preview is and confirmed: InvalidSettingsError with the problems of a text
        the app would refuse, then PasswordRequired, PasswordRefused or SignInThrottled without the administrator's own
        password inside its attempt limit. Nothing is written.
        """
        edit = await self.settings_editor.execute(file, expected_revision, host, text, backup_id)
        await self.settings_confirmation.execute(administrator, edit, password, client)
        return edit

    async def confirm_editor_access(self, running: SignInOffer, saving: UserId | None) -> None:
        """
        The settings this Pipeline's runtime runs on, before a save (`saving`, the administrator) or a reload from disk
        (None) puts them in place, compared with the running settings' sign-in offer: InvalidSettingsError when no
        administrator could sign in to the editor.
        """
        candidate = await self.sign_in_options.execute()
        await self.editor_access.execute(candidate, running, saving)

    async def save_settings_file(self, edit: SettingsEdit, actor: UserId) -> SettingsEdit:
        """Writes a proposal the app starts with, still at its base revision, with a backup and an audit entry naming `actor`."""
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
