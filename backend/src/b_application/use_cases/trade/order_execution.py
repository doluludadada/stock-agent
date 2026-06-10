from a_domain.model.trading.order import Order
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import OrderType, TradeAction
from b_application.schemas.pipeline_context import PipelineContext


class OrderExecution:
    """
    Use Case: Execute BUY / SELL signals.

    HOLD is a decision, not an executable order.
    DEV / TEST behavior belongs to MockExecutionProvider.
    LIVE behavior will belong to ShioajiExecutionProvider.
    """

    def __init__(
        self,
        execution_provider: IExecutionProvider,
        market_clock: IMarketClock,
        logger: ILoggingProvider,
    ):
        self._execution_provider = execution_provider
        self._market_clock = market_clock
        self._logger = logger

    async def execute(self, context: PipelineContext) -> None:
        submitted_count = 0

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

        for signal in orderable_signals:
            if signal.quantity <= 0:
                self._logger.warning(f"Order skipped. Invalid quantity: {signal.stock_id}, quantity={signal.quantity}")
                continue

            order = Order(
                stock_id=signal.stock_id,
                action=signal.action,
                order_type=OrderType.MARKET,
                price=signal.price_at_signal,
                quantity=signal.quantity,
            )

            try:
                order_id = await self._execution_provider.place_order(order)
                submitted_count += 1

                self._logger.success(f"Order processed: {order_id} | {signal.action} {signal.stock_id} x {signal.quantity}")

            except Exception as e:
                error_message = f"Order execution failed: {signal.stock_id}, reason={e}"
                self._logger.error(error_message)
                context.stats.add_error(error_message)

        context.stats.orders_submitted += submitted_count

        # TODO: Phase 2.5 - persist decision_history for BUY / SELL / HOLD.
        # TODO: Phase 2.5 - persist run_history after pipeline execution.
        # TODO: Phase 2.5 - persist position_snapshot after orders are processed.
