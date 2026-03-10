"""
Use Case: Execute Orders.
Translates TradeSignals into broker Orders and submits them via the ExecutionProvider.
"""

from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import OrderAction, OrderType, SignalAction


class OrderExecution:
    def __init__(self, execution_provider: IExecutionProvider, logger: ILoggingProvider):
        self._execution_provider = execution_provider
        self._logger = logger

    async def execute(self, signals: list[TradeSignal]) -> int:
        """
        Processes a list of trade signals and submits them to the execution provider.
        Returns the number of successfully submitted orders.
        """
        if not signals:
            return 0

        submitted_count = 0
        for signal in signals:
            # Skip HOLD signals or signals with 0 quantity
            if signal.action == SignalAction.HOLD or signal.quantity <= 0:
                continue

            # Map SignalAction to OrderAction
            order_action = OrderAction.BUY if signal.action == SignalAction.BUY else OrderAction.SELL

            # Construct the Domain Order
            order = Order(
                stock_id=signal.stock_id,
                action=order_action,
                order_type=OrderType.MARKET,  # Defaulting to Market Order
                quantity=signal.quantity,
                price=signal.price_at_signal,  # Reference price
            )

            try:
                self._logger.info(
                    f"Submitting {order.action.value} order for {order.stock_id} "
                    f"(Qty: {order.quantity}, Ref Price: {order.price})"
                )

                # The execution_provider handles DEV/TEST/LIVE routing internally
                order_id = await self._execution_provider.place_order(order)

                self._logger.success(f"Order placed successfully! Execution ID: {order_id}")
                submitted_count += 1

            except Exception as e:
                self._logger.error(f"Failed to place order for {order.stock_id}: {e}")

        return submitted_count
