from a_domain.model.trading.order import Order
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import (
    IExecutionProvider,
)
from a_domain.types.enums import (
    OrderStatus,
    OrderType,
    TimeInForce,
    TradeAction,
)
from b_application.schemas.pipeline_context import PipelineContext


class OrderExecution:
    """Converts executable signals into broker orders."""

    def __init__(
        self,
        execution_provider: IExecutionProvider,
        market_clock: IMarketClock,
        logger: ILoggingProvider,
    ) -> None:
        self._execution_provider = execution_provider
        self._market_clock = market_clock
        self._logger = logger

    async def execute(
        self,
        context: PipelineContext,
    ) -> None:
        context.orders.clear()

        orderable_signals = [
            signal
            for signal in [
                *context.exit_signals,
                *context.buy_signals,
            ]
            if signal.action != TradeAction.HOLD
        ]

        if not orderable_signals:
            self._logger.info("Order execution skipped. No orderable signals.")
            return

        if not self._market_clock.is_market_open():
            self._logger.warning("Order execution skipped. Market is closed.")
            return

        submitted_count = 0

        for signal in orderable_signals:
            if signal.quantity <= 0:
                self._logger.warning(f"Order skipped. Invalid quantity: {signal.stock_id}, quantity={signal.quantity}")
                continue

            if signal.price_at_signal <= 0:
                self._logger.warning(f"Order skipped. Invalid price: {signal.stock_id}, price={signal.price_at_signal}")
                continue

            order = Order(
                stock_id=signal.stock_id,
                action=signal.action,
                order_type=OrderType.LIMIT,
                quantity=signal.quantity,
                limit_price=signal.price_at_signal,
                time_in_force=TimeInForce.IOC,
            )

            try:
                processed_order = await self._execution_provider.place_order(order)
                context.orders.append(processed_order)

                if processed_order.status in {
                    OrderStatus.SUBMITTED,
                    OrderStatus.FILLED,
                }:
                    submitted_count += 1

                    self._logger.success(
                        f"Order {processed_order.status}: "
                        f"{processed_order.id} | "
                        f"{processed_order.action} "
                        f"{processed_order.stock_id} "
                        f"x {processed_order.quantity}"
                    )
                    continue

                if processed_order.status == OrderStatus.REJECTED:
                    self._logger.warning(f"Order rejected: {processed_order.stock_id}, reason={processed_order.reason}")
                    continue

                if processed_order.status == OrderStatus.FAILED:
                    error_message = f"Order failed: {processed_order.stock_id}, reason={processed_order.reason}"

                    self._logger.error(error_message)
                    context.stats.add_error(error_message)
                    continue

                self._logger.warning(f"Unexpected order status: {processed_order.stock_id}, status={processed_order.status}")

            except Exception as error:
                error_message = f"Order execution failed: {signal.stock_id}, reason={error}"

                self._logger.error(error_message)
                context.stats.add_error(error_message)

        context.stats.orders_submitted += submitted_count

        # TODO: Phase 2.5 - persist decision_history.
        # TODO: Phase 2.5 - persist run_history.
        # TODO: Phase 2.5 - persist position_snapshot.
