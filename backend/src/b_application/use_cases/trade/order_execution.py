# backend/src/b_application/use_cases/trade/order_execution.py

from a_domain.model.trading.order import Order
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import OrderType, SystemEnvironment, TradeAction
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class OrderExecution:
    """
    Use Case: Execute orderable trade signals.
        - BUY and SELL are executable broker actions.
        - HOLD is a decision record, not an order.
    """

    def __init__(
        self,
        execution_provider: IExecutionProvider,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._execution_provider = execution_provider
        self._config = config
        self._logger = logger


    async def execute(self, context: PipelineContext) -> None:

        # Number of orders successfully submitted to the execution provider in this run.
        submitted_count = 0

        # SELL first, BUY second.
        # This avoids buying before exit orders release cash.
        # HOLD signals are intentionally excluded.
        signals = [
            *context.exit_signals,
            *context.buy_signals,
        ]

        for signal in signals:
            if signal.action == TradeAction.HOLD:
                continue

            if signal.quantity <= 0:
                self._logger.warning(f"Skipping {signal.action.value} for {signal.stock_id}: quantity <= 0")
                continue

            if self._config.environment == SystemEnvironment.DEV:
                self._logger.warning(
                    f"[DEV MODE] Skipping real order for {signal.stock_id}. Action={signal.action.value}, Qty={signal.quantity}"
                )
                continue

            order = Order(
                stock_id=signal.stock_id,
                action=signal.action,
                order_type=OrderType.MARKET,
                price=signal.price_at_signal,
                quantity=signal.quantity,
            )
            # Broker-facing instruction derived from a final BUY/SELL TradeSignal.

            try:
                order_id = await self._execution_provider.place_order(order)
                submitted_count += 1

                self._logger.success(f"Order submitted: {order_id} | {signal.action.value} {signal.stock_id} x {signal.quantity}")

            except Exception as e:
                error_message = f"Order failed for {signal.stock_id}: {e}"
                self._logger.error(error_message)
                context.stats.add_error(error_message)

        context.stats.orders_submitted += submitted_count
