from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.trading.order import Order
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import TradeAction, Workflow
from b_application.schemas.config import AppConfig
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.ship.decision_memory import DecisionMemory
from b_application.use_cases.ship.run_history import RunHistory
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.order_execution import OrderExecution


@dataclass(frozen=True)
class ManualBuyRefusal:
    """A confirmed manual BUY that produced no order, and why."""

    stock_id: str
    reason: str


type ManualBuyResult = Order | ManualBuyRefusal
"""The order record when the BUY decision reached OrderExecution (its status and reason say what happened), else the refusal."""


class ManualBuy:
    """
    Use Case: Explicit user BUY override, as its own recorded run.

    It bypasses only the automatic buy threshold. Account loading, realtime refresh, sizing with
    fees, decision recording, the order gates (order mode, market open, price freshness) and the
    broker's own checks all still apply.
    """

    def __init__(
        self,
        run_history: RunHistory,
        account_loader: AccountLoader,
        market_data_collector: MarketDataCollector,
        journal: ITradingJournal,
        decision_memory: DecisionMemory,
        order_execution: OrderExecution,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._run_history = run_history
        self._account_loader = account_loader
        self._market_data_collector = market_data_collector
        self._journal = journal
        self._decision_memory = decision_memory
        self._order_execution = order_execution
        self._entry_rule = config.decision_rule().entry_rule
        self._logger = logger

    async def execute(self, stock: Stock) -> ManualBuyResult:
        async with self._run_history.open(Workflow.MANUAL_BUY) as status:
            status.manual_stocks = [stock]
            status.stocks_cache[stock.stock_id] = stock

            if stock.composite_score is None:
                return self.refuse(stock, "analysis incomplete: no composite score")

            await self._account_loader.execute(status)
            await self._market_data_collector.refresh_realtime([stock], status)

            if stock.current_price is None:
                return self.refuse(stock, "no price: the realtime quote and the daily history are both unavailable")

            signal = self._entry_rule.decide_manual(stock, status.account)

            try:
                await self._journal.save_signals(status.stats.run_id, [signal])

            except Exception as error:
                status.stats.add_error(f"Manual BUY decision not saved: {error}")
                return self.refuse(stock, f"the decision could not be recorded, so no order was sent: {error}")

            status.signals.append(signal)
            status.stats.signals_generated += 1

            if signal.action == TradeAction.HOLD:
                return self.refuse(stock, signal.reason)

            await self._decision_memory.execute(status)
            await self._order_execution.execute([signal], status)

            order = next(order for order in status.orders if order.decision_id == signal.decision_id)
            self._logger.info(f"Manual BUY {stock.stock_id}: {order.status.value.upper()} {order.reason or ''}")

            return order

    def refuse(self, stock: Stock, reason: str) -> ManualBuyRefusal:
        self._logger.warning(f"Manual BUY {stock.stock_id} not placed: {reason}")
        return ManualBuyRefusal(stock_id=stock.stock_id, reason=reason)
