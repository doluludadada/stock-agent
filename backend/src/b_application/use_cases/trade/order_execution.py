from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import OrderType, SystemEnvironment, TradeAction
from b_application.schemas.config import AppConfig


class OrderExecution:
    def __init__(self, execution_provider: IExecutionProvider, config: AppConfig, logger: ILoggingProvider):
        self._execution_provider = execution_provider
        self._config = config
        self._logger = logger

    async def execute(self, signals: list[TradeSignal]) -> int:
        """
        Use Case: Execute Orders.
        Returns the number of successfully submitted orders.
        """
        if not signals:
            return 0

        submitted_count = 0
        for signal in signals:
            if signal.action == TradeAction.HOLD or signal.quantity <= 0:
                continue

            # Check if we are in DEV environment -> Skip real execution
            if self._config.environment == SystemEnvironment.DEV:
                self._logger.warning(
                    f"[DEV MODE] Skipping real order for {signal.stock_id}. "
                    f"Would have placed {signal.action.value} order ."
                    f"for {signal.quantity} shares at {signal.price_at_signal}."
                )
                submitted_count += 1
                continue

            order = Order(
                stock_id=signal.stock_id,
                action=signal.action,
                order_type=OrderType.MARKET,
                quantity=signal.quantity,
                price=signal.price_at_signal,
            )

            try:
                self._logger.info(
                    f"Submitting {order.action.value} order for {order.stock_id} "
                    f"(Qty: {order.quantity}, Ref Price: {order.price})"
                )
                order_id = await self._execution_provider.place_order(order)
                self._logger.success(f"Order placed successfully! Execution ID: {order_id}")
                submitted_count += 1

            except Exception as e:
                self._logger.error(f"Failed to place order for {order.stock_id}: {e}")

        return submitted_count
