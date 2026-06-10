from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import SignalSource, TradeAction, WatchlistType
from b_application.pipeline import AnalysisPipeline
from b_application.schemas.pipeline_context import PipelineContext
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.market_scanner import MarketScanner
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.order_execution import OrderExecution


class TradingWorkflow:
    """
    Exposes the stock-trading operations used by CLI, API and schedulers.

    Each public method represents one complete application operation.
    """

    def __init__(
        self,
        market_scanner: MarketScanner,
        buzz_scanner: BuzzScanner,
        stock_provider: IStockProvider,
        watchlist_repository: IWatchlistRepository,
        account_loader: AccountLoader,
        account_risk_check: AccountRiskCheck,
        technical_filter: TechnicalFilter,
        analysis_pipeline: AnalysisPipeline,
        signals: Signals,
        order_execution: OrderExecution,
        reporting: Reporting,
        logger: ILoggingProvider,
    ) -> None:
        self._market_scanner = market_scanner
        self._buzz_scanner = buzz_scanner
        self._stock_provider = stock_provider
        self._watchlist_repository = watchlist_repository
        self._account_loader = account_loader
        self._account_risk_check = account_risk_check
        self._technical_filter = technical_filter
        self._analysis_pipeline = analysis_pipeline
        self._signals = signals
        self._order_execution = order_execution
        self._reporting = reporting
        self._logger = logger

    async def run_full_cycle(self) -> PipelineContext:
        """
        After-market full-universe analysis.

        Builds the technical watchlist and generates next-session signals.
        It never submits orders.
        """

        context = PipelineContext()

        self._logger.info("Starting full market cycle.")

        await self._account_loader.execute(context)
        await self._account_risk_check.execute(context)
        await self._market_scanner.execute(context)
        await self._technical_filter.execute(context, watchlist_type=WatchlistType.TECHNICAL)
        await self._watchlist_repository.upsert(context.watchlist)
        await self._analysis_pipeline.execute(context)

        if context.survivors or context.emergency_exit_signals:
            await self._signals.execute(context)

        await self._reporting.execute(context)
        context.stats.finish()

        self._logger.info(
            f"Full market cycle completed. "
            f"Scanned={context.stats.total_scanned}, "
            f"Survivors={len(context.survivors)}, "
            f"Signals={context.stats.signals_generated}"
        )

        return context

    async def run_buzz_scan(self) -> PipelineContext:
        """
        Finds currently discussed stocks and evaluates them.

        Only technically qualified buzz stocks are persisted to the
        watchlist.

        Orders are passed to OrderExecution, which must enforce:
        - market-open status
        - valid signal quantity
        - account and broker constraints
        """

        context = PipelineContext()

        self._logger.info("Starting social buzz scan.")

        await self._account_loader.execute(context)
        await self._account_risk_check.execute(context)
        await self._buzz_scanner.execute(context)

        if context.all_stocks:
            await self._market_scanner.execute(context, stocks=context.all_stocks)
            await self._technical_filter.execute(context, watchlist_type=WatchlistType.BUZZ)
            await self._watchlist_repository.upsert(context.watchlist)

        await self._analysis_pipeline.execute(context)

        if context.survivors or context.emergency_exit_signals:
            await self._signals.execute(context)

        await self._order_execution.execute(context)
        await self._reporting.execute(context)
        context.stats.finish()

        self._logger.info(
            f"Social buzz scan completed. "
            f"Candidates={len(context.all_stocks)}, "
            f"Survivors={len(context.survivors)}, "
            f"Orders={context.stats.orders_submitted}"
        )

        return context

    async def run_intraday(self) -> PipelineContext:
        """
        Revalidates held positions and active watchlist candidates
        using current market data before submitting permitted orders.
        """

        context = PipelineContext()

        self._logger.info("Starting intraday trading workflow.")

        await self._account_loader.execute(context)
        await self._account_risk_check.execute(context)

        active_entries = await self._watchlist_repository.get_active()
        context.watchlist = active_entries

        stocks_by_id = {stock.stock_id: stock for stock in context.held_candidates}

        for entry in active_entries:
            if entry.stock_id in stocks_by_id:
                continue

            stock = await self._stock_provider.get_by_id(entry.stock_id)

            if stock is None:
                self._logger.warning(f"Stock not found: {entry.stock_id}")
                continue

            stocks_by_id[stock.stock_id] = stock

        context.all_stocks = list(stocks_by_id.values())

        self._logger.info(
            f"Loaded intraday candidates. "
            f"Held={len(context.held_candidates)}, "
            f"Watchlist={len(active_entries)}, "
            f"Candidates={len(context.all_stocks)}"
        )

        if context.all_stocks:
            await self._market_scanner.execute(context, stocks=context.all_stocks)
            await self._technical_filter.execute(context)

        await self._analysis_pipeline.execute(context)

        if context.survivors or context.emergency_exit_signals:
            await self._signals.execute(context)

        await self._order_execution.execute(context)
        await self._reporting.execute(context)
        context.stats.finish()

        self._logger.info(
            f"Intraday trading completed. "
            f"Candidates={len(context.all_stocks)}, "
            f"Survivors={len(context.survivors)}, "
            f"Orders={context.stats.orders_submitted}"
        )

        return context
    # TODO: Poor logic move to usecase
    async def analyse_specific_stocks(
        self,
        stock_ids: list[str],
    ) -> PipelineContext:
        """
        Produces complete reports for explicitly requested stocks.

        Passing stocks are returned as MANUAL watchlist candidates.
        Persisting them remains an explicit user action.
        """

        context = PipelineContext()

        self._logger.info(f"Starting specific-stock analysis: {stock_ids}")

        stocks: list[Stock] = []

        for stock_id in dict.fromkeys(stock_ids):
            stock = await self._stock_provider.get_by_id(stock_id)

            if stock is None:
                self._logger.warning(f"Stock not found: {stock_id}")
                continue

            stocks.append(stock)

        if stocks:
            await self._market_scanner.execute(context, stocks=stocks)
            await self._technical_filter.execute(context, watchlist_type=WatchlistType.MANUAL)
            await self._analysis_pipeline.execute(context)

        context.stats.finish()

        self._logger.info(
            f"Specific-stock analysis completed. "
            f"Requested={len(stock_ids)}, "
            f"Loaded={len(context.all_stocks)}, "
            f"Analysed={context.stats.ai_analysed}"
        )

        return context

    # TODO: move to usecase
    async def add_manual_watchlist(
        self,
        entries: list[StockWatchlist],
    ) -> None:
        """
        Persists manually selected stocks after the user reviews their reports.
        """

        await self._watchlist_repository.upsert(entries)

        self._logger.info(f"Added {len(entries)} manually selected stocks to the watchlist.")

    # TODO: move to usecase
    async def execute_manual_buy_override(
        self,
        stock_ids: list[str],
        quantity: int,
        context: PipelineContext | None = None,
    ) -> PipelineContext:
        """
        Places explicit user-confirmed BUY orders for reviewed stocks.

        OrderExecution still enforces market-open and signal quantity checks.
        """

        if context is None:
            context = await self.analyse_specific_stocks(stock_ids)

        if quantity <= 0:
            self._logger.warning(f"Manual BUY override skipped. Invalid quantity={quantity}.")
            return context

        context.buy_signals = []

        for stock in context.all_stocks:
            if stock.current_price is None:
                continue

            context.buy_signals.append(
                TradeSignal(
                    stock_id=stock.stock_id,
                    action=TradeAction.BUY,
                    price_at_signal=stock.current_price,
                    source=SignalSource.HYBRID,
                    score=stock.combined_score,
                    reason="MANUAL_BUY_OVERRIDE | User confirmed from CLI after reviewing the report.",
                    quantity=quantity,
                )
            )

        await self._order_execution.execute(context)
        context.stats.finish()

        return context
