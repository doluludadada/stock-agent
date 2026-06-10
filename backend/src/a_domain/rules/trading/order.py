from datetime import datetime

from a_domain.model.trading.order import Order
from a_domain.types.enums import OrderStatus, OrderType, TradeAction


class OrderRules:
    """Validates executable orders and controls order-status transitions."""

    @staticmethod
    def validate_submission(order: Order) -> None:
        if order.status != OrderStatus.PENDING:
            raise ValueError(f"Cannot submit order from status {order.status}")

        if order.action == TradeAction.HOLD:
            raise ValueError("HOLD is not an executable order action")

        if order.order_type == OrderType.LIMIT and order.limit_price is None:
            raise ValueError("LIMIT order requires limit_price")

        if order.order_type == OrderType.MARKET and order.limit_price is not None:
            raise ValueError("MARKET order must not contain limit_price")

        if order.average_filled_price is not None:
            raise ValueError("New order must not contain average_filled_price")

        if order.reason is not None:
            raise ValueError("New order must not contain a terminal reason")

    @staticmethod
    def mark_submitted(order: Order) -> None:
        if order.status != OrderStatus.PENDING:
            raise ValueError(f"Cannot submit order from status {order.status}")

        order.status = OrderStatus.SUBMITTED
        order.reason = None
        order.updated_at = datetime.now()

    @staticmethod
    def mark_filled(
        order: Order,
        filled_price: float,
    ) -> None:
        if order.status not in {
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
        }:
            raise ValueError(f"Cannot fill order from status {order.status}")

        if filled_price <= 0:
            raise ValueError("Filled price must be positive")

        if order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                raise ValueError("LIMIT order requires limit_price")

            if order.action == TradeAction.BUY and filled_price > order.limit_price:
                raise ValueError("BUY fill price cannot exceed limit_price")

            if order.action == TradeAction.SELL and filled_price < order.limit_price:
                raise ValueError("SELL fill price cannot be below limit_price")

        order.status = OrderStatus.FILLED
        order.average_filled_price = filled_price
        order.reason = None
        order.updated_at = datetime.now()

    @staticmethod
    def mark_cancelled(order: Order) -> None:
        if order.status != OrderStatus.SUBMITTED:
            raise ValueError(f"Cannot cancel order from status {order.status}")

        order.status = OrderStatus.CANCELLED
        order.reason = None
        order.updated_at = datetime.now()

    @staticmethod
    def mark_rejected(
        order: Order,
        reason: str,
    ) -> None:
        if order.status != OrderStatus.PENDING:
            raise ValueError(f"Cannot reject order from status {order.status}")

        if not reason.strip():
            raise ValueError("Rejected order requires a reason")

        order.status = OrderStatus.REJECTED
        order.reason = reason
        order.updated_at = datetime.now()

    @staticmethod
    def mark_failed(
        order: Order,
        reason: str,
    ) -> None:
        if order.status not in {
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
        }:
            raise ValueError(f"Cannot fail order from status {order.status}")

        if not reason.strip():
            raise ValueError("Failed order requires a reason")

        order.status = OrderStatus.FAILED
        order.reason = reason
        order.updated_at = datetime.now()
