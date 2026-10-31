from dataclasses import dataclass

from a_domain.model.chat.message import Message
from a_domain.model.market.stock import Stock
from a_domain.model.trading.stock_watchlist import StockWatchlist
from a_domain.model.valuation.market_valuation import MarketValuation
from a_domain.model.valuation.valuation_explanation import ValuationExplanation
from a_domain.model.valuation.valuation_report import ValuationReport
from a_domain.model.valuation.valuation_scan import ValuationScan
from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import AiAnalysisFocus, MessageRole, WatchlistType, Workflow
from a_domain.types.ids import RunId
from b_application.schemas.pipeline_status import PipelineStatus
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
from b_application.use_cases.trade.account_equity import AccountEquity
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.manual_signal import ManualSignal
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.use_cases.trade.order_outcome import OrderOutcome
from b_application.use_cases.trade.order_preparation import OrderPreparation
from b_application.use_cases.trade.watch_stocks import WatchStocks


@dataclass(slots=True)
class CollectSteps:
    market_scanner: MarketScanner
    stock_lookup: StockLookup
    intraday_candidates: IntradayCandidates
    data_collector: MarketDataCollector
    realtime_quote_feed: RealtimeQuoteFeed
    buzz_scanner: BuzzScanner
    news_feed: NewsFeed


@dataclass(slots=True)
class ProcessSteps:
    ai_analyser: AiAnalyser
    technical_filter: TechnicalFilter
    composite_scorer: CompositeScorer
    sentiment_analyser: SentimentAnalyser


@dataclass(slots=True)
class TradingSteps:
    run_history: RunHistory
    account_loader: AccountLoader
    account_equity: AccountEquity
    account_risk_check: AccountRiskCheck
    watch_stocks: WatchStocks
    signals: Signals
    manual_signal: ManualSignal
    decision_memory: DecisionMemory
    order_preparation: OrderPreparation
    order_execution: OrderExecution
    order_outcome: OrderOutcome
    reporting: Reporting


@dataclass(slots=True)
class ChatSteps:
    context_loader: ContextLoader
    ai_processor: AiProcessor
    conversation_repository: IConversationRepository
    dispatcher: Dispatcher
    reset_commands: frozenset[str]
    market_clock: IMarketClock


@dataclass(slots=True)
class ValuationSteps:
    """
    Everything the P/E valuation workflows reach. It holds no order, signal, account or watchlist dependency, and the
    valuation workflows use nothing else, so nothing they reach can place an order or write the watchlist. The
    order-gate check walks this object graph and those workflows to keep it that way.
    """

    stock_provider: IStockProvider
    fundamentals_feed: FundamentalsFeed
    data_collector: MarketDataCollector
    technical_filter: TechnicalFilter
    news_feed: NewsFeed
    valuation_explainer: ValuationExplainer
    technical_settings_repository: ITechnicalSettingsRepository
    market_clock: IMarketClock
    scenario_spread: float
    close_max_missed_sessions: int


@dataclass(slots=True)
class Pipeline:
    """
    Exposes the operations used by the CLI, the Web API and the LINE webhook. Each public method is one workflow.

    Technical settings are loaded once at the beginning of each trading workflow. The loaded snapshot remains
    fixed until that workflow completes.

    Each trading workflow runs inside RunHistory.execute, so it has one run id and a saved run record. The Web API
    starts Full Cycle and specific-stock analysis under a run id it already returned to its caller. The valuation
    workflows record no run and use only `valuation`.
    """

    collect: CollectSteps
    process: ProcessSteps
    trading: TradingSteps
    chat: ChatSteps
    valuation: ValuationSteps
    technical_settings_repository: ITechnicalSettingsRepository
    logger: ILoggingProvider

    async def run_full_cycle(self, run_id: RunId | None = None) -> PipelineStatus:
        """After-market full-universe analysis. It never submits orders."""
        settings = await self.technical_settings_repository.load()
        strategy = settings.active_strategy

        async with self.trading.run_history.execute(Workflow.FULL_CYCLE, run_id) as status:
            self.logger.info(f"Starting full market cycle. Strategy={strategy.strategy_id}.")

            await self.trading.account_loader.execute(status)
            await self.collect.market_scanner.execute(status)
            await self.collect.data_collector.execute(status.universe_stocks, status)
            status.survivors = await self.process.technical_filter.execute(status.universe_stocks, status, strategy)
            await self.collect.news_feed.execute(status.survivors, status)
            await self.process.ai_analyser.execute(status.survivors, status, AiAnalysisFocus.FUNDAMENTAL)
            self.process.composite_scorer.execute(status.survivors)
            status.watchlist = (await self.trading.watch_stocks.execute(status.survivors, WatchlistType.TECHNICAL)).watchlist
            self.trading.account_equity.execute(status)
            await self.trading.signals.execute(status.watchlist, status)
            await self.trading.decision_memory.execute(status)
            await self.trading.reporting.execute(status)

        self.logger.info(
            f"Full market cycle completed. "
            f"Scanned={status.stats.total_scanned}, "
            f"Survivors={len(status.survivors)}, "
            f"Signals={status.stats.signals_generated}."
        )

        return status

    async def run_buzz_scan(self) -> PipelineStatus:
        """Runs short-term social momentum analysis. Sentiment is report only, so it runs after every trading step."""
        strategy = (await self.technical_settings_repository.load()).buzz_strategy

        async with self.trading.run_history.execute(Workflow.BUZZ_SCAN) as status:
            self.logger.info(f"Starting social buzz cycle. Strategy={strategy.strategy_id}, AI focus={AiAnalysisFocus.MOMENTUM}.")
            await self.trading.account_loader.execute(status)
            await self.collect.realtime_quote_feed.execute(status.held_stocks, status)
            self.trading.account_equity.execute(status)
            await self.trading.account_risk_check.execute(status)
            await self._execute_orders(status)
            await self.collect.buzz_scanner.execute(status)
            status.stats.total_scanned = len(status.buzz_stocks)
            await self.collect.data_collector.execute(status.buzz_stocks, status)
            status.survivors = await self.process.technical_filter.execute(status.buzz_stocks, status, strategy)
            status.watchlist = (await self.trading.watch_stocks.execute(status.survivors, WatchlistType.BUZZ)).watchlist
            await self.collect.news_feed.execute(status.survivors, status)
            await self.process.ai_analyser.execute(status.survivors, status, AiAnalysisFocus.MOMENTUM)
            self.process.composite_scorer.execute(status.survivors)
            await self.collect.realtime_quote_feed.execute(status.survivors, status)
            await self.trading.signals.execute(status.watchlist, status)
            await self.trading.decision_memory.execute(status)
            await self._execute_orders(status)
            await self.process.sentiment_analyser.execute(status.buzz_stocks, status)
            await self.trading.reporting.execute(status)
        self.logger.info(
            f"Social buzz cycle completed. Candidates={len(status.buzz_stocks)}, Qualified={len(status.survivors)}, "
            f"Orders={status.stats.orders_submitted}."
        )
        return status

    async def run_intraday(self) -> PipelineStatus:
        """Revalidates held and watched stocks before order submission."""
        strategy = (await self.technical_settings_repository.load()).active_strategy

        async with self.trading.run_history.execute(Workflow.INTRADAY) as status:
            self.logger.info(f"Starting intraday trading cycle. Strategy={strategy.strategy_id}.")
            await self.trading.account_loader.execute(status)
            candidates = await self.collect.intraday_candidates.execute(status)
            await self.collect.realtime_quote_feed.execute(candidates, status)
            self.trading.account_equity.execute(status)
            await self.trading.account_risk_check.execute(status)
            await self._execute_orders(status)
            status.stats.total_scanned = len(candidates)
            blocked_stock_ids = status.risk_blocked_stock_ids | status.stale_stock_ids
            analysis_candidates = [stock for stock in candidates if stock.stock_id not in blocked_stock_ids]
            await self.collect.data_collector.execute(analysis_candidates, status)
            technical_candidates = [stock for stock in analysis_candidates if stock.ohlcv]
            status.survivors = await self.process.technical_filter.execute(technical_candidates, status, strategy)
            held_candidates = [stock for stock in technical_candidates if status.account.position_for(stock.stock_id) is not None]
            decision_candidates = list({stock.stock_id: stock for stock in [*status.survivors, *held_candidates]}.values())
            await self.collect.news_feed.execute(decision_candidates, status)
            await self.process.ai_analyser.execute(decision_candidates, status, AiAnalysisFocus.FUNDAMENTAL)
            self.process.composite_scorer.execute(decision_candidates)
            await self.collect.realtime_quote_feed.execute(decision_candidates, status)
            await self.trading.signals.execute(StockWatchlist(willing_stocks=decision_candidates), status)
            await self.trading.decision_memory.execute(status)
            await self._execute_orders(status)
            await self.trading.reporting.execute(status)

        self.logger.info("Intraday trading cycle completed.")
        return status

    async def analyse_specific_stocks(self, stock_ids: list[str], run_id: RunId | None = None) -> PipelineStatus:
        """Produces complete reports for explicitly requested stocks."""
        settings = await self.technical_settings_repository.load()
        strategy = settings.active_strategy

        async with self.trading.run_history.execute(Workflow.SPECIFIC_STOCKS, run_id) as status:
            self.logger.info(f"Starting specific-stock analysis: {stock_ids}")

            status.manual_stocks = await self.collect.stock_lookup.execute(stock_ids, status)

            if not status.manual_stocks:
                self.logger.info("Specific-stock analysis completed. No requested stocks were loaded.")
                return status

            await self.collect.data_collector.execute(status.manual_stocks, status)

            status.survivors = await self.process.technical_filter.execute(status.manual_stocks, status, strategy)

            # Human override: Technical failure does not stop News, AI, or reporting.
            await self.collect.news_feed.execute(status.manual_stocks, status)
            await self.process.ai_analyser.execute(status.manual_stocks, status, AiAnalysisFocus.FUNDAMENTAL)
            self.process.composite_scorer.execute(status.manual_stocks)
            await self.trading.reporting.execute(status)

        self.logger.info("Specific-stock analysis completed.")

        return status

    async def buy_manually(self, stock: Stock) -> PipelineStatus:
        """
        The user's confirmed BUY of one analysed stock, as its own recorded run. It bypasses only the automatic buy
        threshold: account loading, realtime refresh, sizing with fees, decision recording, the order gates (order
        mode, market open, price freshness) and the broker's own checks all still apply.

        status.manual_buy_refusal says why no order was sent; otherwise status.orders holds the one order.
        """
        async with self.trading.run_history.execute(Workflow.MANUAL_BUY) as status:
            status.manual_stocks = [stock]
            status.stocks_cache[stock.stock_id] = stock

            if stock.composite_score is None:
                status.manual_buy_refusal = "analysis incomplete: no composite score"
                self.logger.warning(f"Manual BUY {stock.stock_id} not placed: {status.manual_buy_refusal}")
                return status

            await self.trading.account_loader.execute(status)
            await self.collect.realtime_quote_feed.execute([stock], status)
            self.trading.account_equity.execute(status)
            await self.trading.manual_signal.execute(stock, status)
            await self.trading.decision_memory.execute(status)
            await self._execute_orders(status)

        self.logger.info(f"Manual BUY {stock.stock_id} completed. Orders={len(status.orders)}.")

        return status

    async def _execute_orders(self, status: PipelineStatus) -> None:
        """
        The order steps of the trading workflows: each BUY and SELL decision of the run that has no order yet, one at a
        time in decision order, is gated and recorded right before it is sent (so OrderRule measures its quote's age at
        submission), then sent, then taken into the run. Buzz and Intraday run it twice: right after the stop-loss
        check, while those quotes are fresh, and at the end.
        """
        for signal in status.signals:
            order = await self.trading.order_preparation.execute(signal, status)

            if order is None:
                continue

            order = await self.trading.order_execution.execute(order, status)
            await self.trading.order_outcome.execute(order, status)

    async def load_market_valuation(self) -> MarketValuation:
        """Every listed and OTC stock with its official close, TTM EPS and industry: bulk sources, a few requests."""
        status = PipelineStatus.for_valuation(self.valuation.market_clock.now())
        stocks = await self.valuation.stock_provider.get_all()
        closes = await self.valuation.stock_provider.get_latest_closes()

        await self.valuation.fundamentals_feed.execute(stocks, status)

        return MarketValuation.of(
            stocks=stocks,
            closes=closes,
            last_closed_session=self.valuation.market_clock.last_closed_session(),
            max_missed_sessions=self.valuation.close_max_missed_sessions,
            scenario_spread=self.valuation.scenario_spread,
            source_warnings=tuple(status.stats.errors),
        )

    async def confirm_valuation_technical(self, scan: ValuationScan) -> ValuationScan:
        """The undervalued scan's second step: the active technical strategy, applied exactly as the trading workflows apply it."""
        strategy = (await self.valuation.technical_settings_repository.load()).active_strategy
        status = PipelineStatus.for_valuation(self.valuation.market_clock.now())
        stocks = [report.stock for report in scan.survivors]

        await self.valuation.data_collector.execute(stocks, status)
        await self.valuation.technical_filter.execute([stock for stock in stocks if stock.ohlcv], status, strategy)

        return scan.after_technical_step(strategy.strategy_id)

    async def explain_valuation(self, report: ValuationReport) -> ValuationExplanation:
        """The domain computed every number; the AI explains them with the stock's news."""
        if not report.stock.articles:
            await self.valuation.news_feed.execute([report.stock], PipelineStatus.for_valuation(self.valuation.market_clock.now()))

        return await self.valuation.valuation_explainer.execute(report)

    async def reply_to_chat(self, user_id: str, content: str) -> None:
        """Answers one chat message: a reset command clears the conversation, any other text gets the AI's reply."""
        conversation = await self.chat.context_loader.execute(user_id)
        now = self.chat.market_clock.now()

        if content.strip() in self.chat.reset_commands:
            await self.chat.conversation_repository.save(conversation.clear_history(now=now))
            self.logger.info(f"Conversation memory cleared for user_id: {user_id}")
            reset_reply = Message(role=MessageRole.ASSISTANT, content="✨ Memory cleared. Let's start over.", timestamp=now)
            await self.chat.dispatcher.execute(user_id, (reset_reply,))
            return

        conversation = conversation.add_messages([Message(role=MessageRole.USER, content=content, timestamp=now)], now=now)
        replies = await self.chat.ai_processor.execute(conversation)

        await self.chat.conversation_repository.save(conversation.add_messages(replies, now=self.chat.market_clock.now()))
        await self.chat.dispatcher.execute(user_id, replies)
