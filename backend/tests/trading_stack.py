from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from a_domain.model.analysis.ai_analysis_report import AiAnalysisReport
from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.signal import TradeSignal
from a_domain.types.enums import ExecutionProvider, OrderMode, Workflow
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.ship.decision_memory import DecisionMemory
from b_application.use_cases.ship.run_history import RunHistory
from b_application.use_cases.trade.account_history import AccountHistory
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.manual_buy import ManualBuy
from b_application.use_cases.trade.order_execution import OrderExecution
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.trading_journal import TradingJournal
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider

MONDAY_10_00 = datetime(2026, 10, 19, 10, 0, tzinfo=TAIWAN_TIMEZONE)


class SilentLogger:
    def _drop(self, message: str) -> None:
        return None

    info = warning = debug = critical = error = success = trace = exception = _drop


def run_status(workflow: Workflow = Workflow.INTRADAY) -> PipelineStatus:
    return PipelineStatus(
        stats=SystemStats(workflow=workflow, execution_provider=ExecutionProvider.MOCK, order_mode=OrderMode.MOCK_ONLY)
    )


class MovableClock(TaiwanMarketClock):
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


@dataclass
class QuoteFeed:
    """IOhlcvProvider with prices the test sets: one realtime bar and a daily history per stock."""

    realtime: dict[str, Ohlcv] = field(default_factory=dict)
    daily: dict[str, list[Ohlcv]] = field(default_factory=dict)

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        return {stock.stock_id: self.realtime[stock.stock_id] for stock in stocks if stock.stock_id in self.realtime}

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        return {stock.stock_id: self.daily[stock.stock_id] for stock in stocks if stock.stock_id in self.daily}


class StockDirectory:
    async def get_all(self) -> list[Stock]:
        return []

    async def get_by_id(self, stock_id: str) -> Stock | None:
        return Stock(stock_id=stock_id)


class ForgetfulKnowledge:
    async def search(self, query: str, limit: int = 3) -> str:
        return ""

    async def save_decision(self, stock: Stock, signal: TradeSignal) -> None:
        return None


def bar(at: datetime, close: float) -> Ohlcv:
    return Ohlcv(ts=at, open=close, high=close, low=close, close=close, volume=5000)


def analysed_stock(stock_id: str = "2330", composite_score: int | None = 90) -> Stock:
    """A stock as menu 4 leaves it: daily history, technical and AI reports, composite score."""
    return Stock(
        stock_id=stock_id,
        ohlcv=[bar(MONDAY_10_00 - timedelta(days=3, hours=-3, minutes=-30), 98)],
        technical_report=TechnicalReport(score=90, soft_failures=["volume_expansion"], observations=["golden_cross: detected"]),
        ai_report=AiAnalysisReport(score=90, bullish_factors=["AI demand"], bearish_factors=[], summary="Strong", raw_response="{}"),
        composite_score=composite_score,
    )


@dataclass
class TradingStack:
    """The real manual-BUY path on a real SQLite file: ManualBuy, OrderExecution, the mock broker and the journal."""

    config: AppConfig
    db: DatabaseConnector
    clock: MovableClock
    quotes: QuoteFeed
    journal: TradingJournal
    broker: MockExecutionProvider
    run_history: RunHistory
    order_execution: OrderExecution
    manual_buy: ManualBuy
    account_history: AccountHistory


async def open_stack(tmp_path: Path, configure=lambda config: None, journal: TradingJournal | None = None) -> TradingStack:
    config = AppConfig(project_root=tmp_path)
    configure(config)
    logger = SilentLogger()
    db = DatabaseConnector(config=config, logger=logger)
    await db.init_db()

    clock = MovableClock(MONDAY_10_00)
    quotes = QuoteFeed(realtime={"2330": bar(MONDAY_10_00 - timedelta(minutes=1), 100)})
    journal = journal or TradingJournal(db=db)
    broker = MockExecutionProvider(db=db, config=config, logger=logger)
    stocks = StockDirectory()

    run_history = RunHistory(journal=journal, config=config, logger=logger)
    account_loader = AccountLoader(
        execution_provider=broker, stock_provider=stocks, journal=journal, market_clock=clock, logger=logger
    )
    collector = MarketDataCollector(ohlcv_provider=quotes, market_clock=clock, config=config, logger=logger)
    order_execution = OrderExecution(
        execution_provider=broker, journal=journal, account_loader=account_loader, market_clock=clock, config=config, logger=logger
    )
    manual_buy = ManualBuy(
        run_history=run_history,
        account_loader=account_loader,
        market_data_collector=collector,
        journal=journal,
        decision_memory=DecisionMemory(knowledge_repository=ForgetfulKnowledge(), logger=logger),
        order_execution=order_execution,
        config=config,
        logger=logger,
    )
    account_history = AccountHistory(
        execution_provider=broker,
        journal=journal,
        stock_provider=stocks,
        ohlcv_provider=quotes,
        market_clock=clock,
        config=config,
        logger=logger,
    )

    return TradingStack(config, db, clock, quotes, journal, broker, run_history, order_execution, manual_buy, account_history)
