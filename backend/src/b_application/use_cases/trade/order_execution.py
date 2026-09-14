from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import (
    ExecutionProvider,
    OrderMode,
    OrderStatus,
    OrderType,
    TimeInForce,
    TradeAction,
)
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


# TODO: Needa check this file later.
class OrderExecution:
    """
    Converts executable trading signals into broker orders.

    Responsibilities:
    - ignore HOLD signals
    - enforce configured order mode
    - ensure market is open
    - reject stale market data
    - reject invalid signal quantity or price
    - construct broker orders
    - delegate final validation and execution to IExecutionProvider
    """

    def __init__(
        self,
        execution_provider: IExecutionProvider,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._execution_provider = execution_provider
        self._market_clock = market_clock
        self._execution_provider_type = config.trading.execution_provider
        self._order_mode = config.trading.order_mode
        self._logger = logger

    async def execute(
        self,
        signals: list[TradeSignal],
        status: PipelineStatus,
    ) -> None:
        orderable_signals = [
            signal
            for signal in signals
            if signal.action != TradeAction.HOLD
        ]

        if not orderable_signals:
            self._logger.info(
                "Order execution skipped. No orderable signals."
            )
            return

        if not self.is_execution_allowed(status):
            return

        if not self._market_clock.is_market_open():
            self._logger.warning(
                "Order execution skipped. Market is closed."
            )
            return

        for signal in orderable_signals:
            if signal.stock_id in status.stale_stock_ids:
                self._logger.warning(
                    f"Order skipped. Market data is stale: "
                    f"{signal.stock_id}"
                )
                continue

            await self.execute_signal(
                signal,
                status,
            )

    def is_execution_allowed(
        self,
        status: PipelineStatus,
    ) -> bool:
        if self._order_mode == OrderMode.DISABLED:
            self._logger.warning(
                "Order execution disabled by configuration."
            )
            return False

        if (
            self._order_mode == OrderMode.MOCK_ONLY
            and self._execution_provider_type != ExecutionProvider.MOCK
        ):
            return self.reject_invalid_mode(
                status,
                "MOCK_ONLY requires MockExecutionProvider",
            )

        if (
            self._order_mode == OrderMode.LIVE
            and self._execution_provider_type == ExecutionProvider.MOCK
        ):
            return self.reject_invalid_mode(
                status,
                "LIVE order mode cannot use MockExecutionProvider",
            )

        return True

    def reject_invalid_mode(
        self,
        status: PipelineStatus,
        message: str,
    ) -> bool:
        self._logger.error(message)
        status.stats.add_error(message)

        return False

    async def execute_signal(
        self,
        signal: TradeSignal,
        status: PipelineStatus,
    ) -> None:
        if signal.quantity <= 0:
            self._logger.warning(
                f"Order skipped. Invalid quantity: "
                f"{signal.stock_id}, quantity={signal.quantity}"
            )
            return

        if signal.price_at_signal <= 0:
            self._logger.warning(
                f"Order skipped. Invalid price: "
                f"{signal.stock_id}, price={signal.price_at_signal}"
            )
            return

        order = Order(
            stock_id=signal.stock_id,
            action=signal.action,
            order_type=OrderType.LIMIT,
            quantity=signal.quantity,
            limit_price=signal.price_at_signal,
            time_in_force=TimeInForce.IOC,
        )

        await self.submit_order(
            order,
            status,
        )

    async def submit_order(
        self,
        order: Order,
        status: PipelineStatus,
    ) -> None:
        try:
            processed_order = await self._execution_provider.place_order(
                order
            )

        except Exception as error:
            message = (
                f"Order execution failed: "
                f"{order.stock_id}, error={error}"
            )
            self._logger.error(message)
            status.stats.add_error(message)
            return

        status.orders.append(processed_order)

        if processed_order.status in {
            OrderStatus.SUBMITTED,
            OrderStatus.FILLED,
        }:
            status.stats.orders_submitted += 1
            self._logger.success(
                f"Order {processed_order.status}: "
                f"{processed_order.stock_id} "
                f"x {processed_order.quantity}"
            )
            return

        self.handle_terminal_order(
            processed_order,
            status,
        )

    def handle_terminal_order(
        self,
        order: Order,
        status: PipelineStatus,
    ) -> None:
        if order.status == OrderStatus.REJECTED:
            self._logger.warning(
                f"Order rejected: "
                f"{order.stock_id}, reason={order.reason}"
            )
            return

        if order.status == OrderStatus.FAILED:
            message = (
                f"Order failed: "
                f"{order.stock_id}, reason={order.reason}"
            )
            self._logger.error(message)
            status.stats.add_error(message)

        # TODO: Phase 2.5 - persist decision_history.
        # TODO: Phase 2.5 - persist run_history.
        # TODO: Phase 2.5 - persist position_snapshot.
