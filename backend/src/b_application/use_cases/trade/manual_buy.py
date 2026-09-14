from datetime import UTC, datetime

from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.rules.trading.sizing import SizingRule
from a_domain.types.enums import SignalSource, TradeAction
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.collect.market_data_collector import (
    MarketDataCollector,
)
from b_application.use_cases.ship.decision_memory import DecisionMemory
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.order_execution import OrderExecution


class ManualBuy:
    """
    Use Case: Explicit user BUY override.

    This bypasses the automatic EntryRule BUY threshold.

    It does not bypass:
    - account loading
    - realtime data freshness
    - position sizing
    - order-mode validation
    - market-open validation
    - order validation
    - execution-provider validation
    """

    def __init__(
        self,
        account_loader: AccountLoader,
        market_data_collector: MarketDataCollector,
        signal_repository: ISignalRepository,
        decision_memory: DecisionMemory,
        order_execution: OrderExecution,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._account_loader = account_loader
        self._market_data_collector = market_data_collector
        self._signal_repository = signal_repository
        self._decision_memory = decision_memory
        self._order_execution = order_execution
        self._logger = logger

        self._sizing_rule = SizingRule(
            risk_per_trade_pct=config.analysis.risk_per_trade_pct,
            stop_loss_pct=config.analysis.stop_loss_pct,
            lot_size=1,
        )

    async def execute(
        self,
        stock: Stock,
    ) -> PipelineStatus:
        status = PipelineStatus(
            manual_stocks=[stock],
            stocks_cache={stock.stock_id: stock},
        )

        if stock.composite_score is None:
            return self.reject(
                status,
                f"Manual BUY rejected. Analysis incomplete: {stock.stock_id}",
            )

        await self._account_loader.execute(status)
        await self._market_data_collector.refresh_realtime(
            [stock],
            status,
        )

        current_price = stock.current_price

        if (
            stock.stock_id in status.stale_stock_ids
            or current_price is None
            or current_price <= 0
        ):
            return self.reject(
                status,
                f"Manual BUY rejected. "
                f"Realtime price unavailable: {stock.stock_id}",
            )

        quantity = self._sizing_rule.calculate(
            account=status.account,
            price=current_price,
        )

        if quantity <= 0:
            return self.reject(
                status,
                f"Manual BUY rejected. No valid quantity: {stock.stock_id}",
            )

        signal = self.create_signal(
            stock,
            current_price,
            quantity,
        )

        await self._signal_repository.save(signal)
        status.signals.append(signal)
        status.stats.signals_generated += 1

        await self._decision_memory.execute(status)
        await self._order_execution.execute([signal], status)

        status.stats.finish()

        self._logger.info(
            f"Manual BUY completed: {stock.stock_id}, "
            f"quantity={quantity}, "
            f"price={stock.current_price}"
        )

        return status

    def create_signal(
        self,
        stock: Stock,
        current_price: float,
        quantity: int,
    ) -> TradeSignal:
        if stock.composite_score is None:
            raise ValueError(
                "Manual BUY requires composite score"
            )

        return TradeSignal(
            stock_id=stock.stock_id,
            action=TradeAction.BUY,
            price_at_signal=current_price,
            source=SignalSource.MANUAL,
            score=stock.composite_score,
            reason="Manual BUY override confirmed by user.",
            quantity=quantity,
            generated_at=datetime.now(UTC),
        )

    def reject(
        self,
        status: PipelineStatus,
        message: str,
    ) -> PipelineStatus:
        status.stats.add_error(message)
        status.stats.finish()
        self._logger.warning(message)

        return status
