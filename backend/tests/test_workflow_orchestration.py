from datetime import date, datetime, timezone
from typing import Any, cast

import pytest

from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.types.enums import SignalSource, TradeAction, WatchlistType
from b_application.schemas.pipeline_context import PipelineContext
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.workflow import TradingWorkflow


class FakeLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.warnings: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)
        self.messages.append(message)

    def debug(self, message: str) -> None:
        self.messages.append(message)

    def critical(self, message: str) -> None:
        self.messages.append(message)

    def error(self, message: str) -> None:
        self.messages.append(message)

    def success(self, message: str) -> None:
        self.messages.append(message)

    def trace(self, message: str) -> None:
        self.messages.append(message)

    def exception(self, message: str) -> None:
        self.messages.append(message)


class NoopUseCase:
    async def execute(self, context: PipelineContext) -> None:
        return None


class FakeAccountLoader:
    def __init__(self, held: list[Stock] | None = None) -> None:
        self._held = held or []

    async def execute(self, context: PipelineContext) -> None:
        context.held_candidates = list(self._held)


class FakeBuzzScanner:
    def __init__(self, stocks: list[Stock]) -> None:
        self._stocks = stocks

    async def execute(self, context: PipelineContext) -> None:
        context.all_stocks = list(self._stocks)


class FakeMarketScanner:
    def __init__(self) -> None:
        self.enriched_ids: list[str] = []

    async def execute(self, context: PipelineContext, stocks: list[Stock] | None = None) -> None:
        if stocks is not None:
            context.all_stocks = list(stocks)
        self.enriched_ids = [stock.stock_id for stock in context.all_stocks]


class FakeTechnicalFilter:
    def __init__(self, survivor_ids: set[str] | None = None) -> None:
        self._survivor_ids = survivor_ids

    async def execute(self, context: PipelineContext, watchlist_type: WatchlistType | None = None) -> None:
        if self._survivor_ids is None:
            context.survivors = list(context.all_stocks)
        else:
            context.survivors = [stock for stock in context.all_stocks if stock.stock_id in self._survivor_ids]

        if watchlist_type is not None:
            context.watchlist = [StockWatchlist(stock_id=stock.stock_id, type=watchlist_type) for stock in context.survivors]


class FakeStockProvider:
    def __init__(self, stocks: list[Stock]) -> None:
        self._stocks = {stock.stock_id: stock for stock in stocks}

    async def get_by_id(self, stock_id: str) -> Stock | None:
        return self._stocks.get(stock_id)


class FakeWatchlistRepository:
    def __init__(self, active: list[StockWatchlist] | None = None) -> None:
        self._active = active or []
        self.upserted: list[StockWatchlist] = []

    async def get_active(self) -> list[StockWatchlist]:
        return list(self._active)

    async def upsert(self, entries: list[StockWatchlist]) -> None:
        self.upserted = list(entries)


class FakeOrderExecution:
    def __init__(self) -> None:
        self.called = False

    async def execute(self, context: PipelineContext) -> None:
        self.called = True


class ClosedMarketClock:
    @property
    def timezone(self):
        return timezone.utc

    def now(self) -> datetime:
        return datetime(2026, 6, 6, 14, 0, tzinfo=timezone.utc)

    def today(self) -> date:
        return self.now().date()

    def to_market_datetime(self, value: datetime) -> datetime:
        return value

    def to_trading_date(self, value: datetime) -> date:
        return value.date()

    def history_window(self, lookback_days: int) -> tuple[datetime, datetime]:
        now = self.now()
        return now, now

    def is_market_open(self) -> bool:
        return False


class FailingExecutionProvider:
    async def place_order(self, order) -> str:
        raise AssertionError("closed-market order should not be submitted")


def build_workflow(
    *,
    market_scanner: FakeMarketScanner,
    buzz_scanner: FakeBuzzScanner | None = None,
    account_loader: FakeAccountLoader | None = None,
    technical_filter: FakeTechnicalFilter | None = None,
    watchlist_repository: FakeWatchlistRepository | None = None,
    stock_provider: FakeStockProvider | None = None,
    order_execution: FakeOrderExecution | None = None,
) -> TradingWorkflow:
    return TradingWorkflow(
        market_scanner=cast(Any, market_scanner),
        buzz_scanner=cast(Any, buzz_scanner or FakeBuzzScanner([])),
        stock_provider=cast(Any, stock_provider or FakeStockProvider([])),
        watchlist_repository=cast(Any, watchlist_repository or FakeWatchlistRepository()),
        account_loader=cast(Any, account_loader or FakeAccountLoader()),
        account_risk_check=cast(Any, NoopUseCase()),
        technical_filter=cast(Any, technical_filter or FakeTechnicalFilter()),
        analysis_pipeline=cast(Any, NoopUseCase()),
        signals=cast(Any, NoopUseCase()),
        order_execution=cast(Any, order_execution or FakeOrderExecution()),
        reporting=cast(Any, NoopUseCase()),
        logger=cast(Any, FakeLogger()),
    )


@pytest.mark.asyncio
async def test_buzz_scan_persists_only_technical_survivors() -> None:
    stock_a = Stock(stock_id="2330")
    stock_b = Stock(stock_id="2317")
    market_scanner = FakeMarketScanner()
    watchlist_repository = FakeWatchlistRepository()
    workflow = build_workflow(
        market_scanner=market_scanner,
        buzz_scanner=FakeBuzzScanner([stock_a, stock_b]),
        technical_filter=FakeTechnicalFilter({"2330"}),
        watchlist_repository=watchlist_repository,
    )

    context = await workflow.run_buzz_scan()

    assert [entry.stock_id for entry in watchlist_repository.upserted] == ["2330"]
    assert watchlist_repository.upserted[0].type == WatchlistType.BUZZ
    assert [stock.stock_id for stock in context.survivors] == ["2330"]
    assert market_scanner.enriched_ids == ["2330", "2317"]


@pytest.mark.asyncio
async def test_intraday_loads_held_positions_and_active_watchlist() -> None:
    held_stock = Stock(stock_id="2330")
    watched_stock = Stock(stock_id="2317")
    market_scanner = FakeMarketScanner()
    order_execution = FakeOrderExecution()
    workflow = build_workflow(
        market_scanner=market_scanner,
        account_loader=FakeAccountLoader([held_stock]),
        stock_provider=FakeStockProvider([held_stock, watched_stock]),
        watchlist_repository=FakeWatchlistRepository(
            [
                StockWatchlist(stock_id="2317", type=WatchlistType.TECHNICAL),
                StockWatchlist(stock_id="2330", type=WatchlistType.BUZZ),
            ]
        ),
        order_execution=order_execution,
    )

    context = await workflow.run_intraday()

    assert [stock.stock_id for stock in context.all_stocks] == ["2330", "2317"]
    assert market_scanner.enriched_ids == ["2330", "2317"]
    assert order_execution.called is True


@pytest.mark.asyncio
async def test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders() -> None:
    stock = Stock(stock_id="2330")
    market_scanner = FakeMarketScanner()
    order_execution = FakeOrderExecution()
    workflow = build_workflow(
        market_scanner=market_scanner,
        stock_provider=FakeStockProvider([stock]),
        technical_filter=FakeTechnicalFilter({"2330"}),
        order_execution=order_execution,
    )

    context = await workflow.analyse_specific_stocks(["2330"])

    assert [stock.stock_id for stock in context.all_stocks] == ["2330"]
    assert [stock.stock_id for stock in context.survivors] == ["2330"]
    assert [entry.stock_id for entry in context.watchlist] == ["2330"]
    assert context.watchlist[0].type == WatchlistType.MANUAL
    assert context.stats.signals_generated == 0
    assert order_execution.called is False


@pytest.mark.asyncio
async def test_order_execution_skips_closed_market_orders() -> None:
    logger = FakeLogger()
    order_execution = OrderExecution(
        execution_provider=cast(Any, FailingExecutionProvider()),
        market_clock=cast(Any, ClosedMarketClock()),
        logger=cast(Any, logger),
    )
    context = PipelineContext(
        buy_signals=[
            TradeSignal(
                stock_id="2330",
                action=TradeAction.BUY,
                price_at_signal=100,
                source=SignalSource.HYBRID,
                score=80,
                reason="test",
                quantity=1,
            )
        ]
    )

    await order_execution.execute(context)

    assert context.stats.orders_submitted == 0
    assert "Order execution skipped. Market is closed." in logger.warnings
