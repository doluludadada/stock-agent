from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlmodel import col

from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.rules.trading.order import OrderRules
from a_domain.types.enums import OrderStatus, OrderType, TimeInForce, TradeAction
from b_application.schemas.config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.mock_trading_dto import MockCash, MockOrder, MockPosition
from c_infrastructure.trading.mock.constants import MockLogMessage, MockRejectReason


# TODO: needa check
class MockExecutionProvider(IExecutionProvider):
    """Database-backed broker simulator."""

    def __init__(
        self,
        db: DatabaseConnector,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._db = db
        self._config = config
        self._logger = logger
        self._account_id = config.mock_trading.account_id
        self._initial_cash = config.mock_trading.initial_cash

    async def place_order(
        self,
        order: Order,
    ) -> Order:
        await self._ensure_account()

        try:
            OrderRules.validate_submission(order)

        except ValueError as error:
            OrderRules.mark_rejected(order, str(error))
            await self._save_order(order)

            self._logger.warning(f"{MockLogMessage.ORDER_REJECTED} {order.action} {order.stock_id}: {order.reason}")
            return order

        try:
            if order.order_type != OrderType.LIMIT:
                OrderRules.mark_rejected(
                    order,
                    MockRejectReason.UNSUPPORTED_ORDER_TYPE,
                )
                await self._save_order(order)

                self._logger.warning(f"{MockLogMessage.ORDER_REJECTED} {order.action} {order.stock_id}: {order.reason}")
                return order

            if order.time_in_force == TimeInForce.ROD:
                OrderRules.mark_submitted(order)
                await self._save_order(order)

                self._logger.info(
                    f"{MockLogMessage.ORDER_SUBMITTED} {order.action} {order.stock_id} x {order.quantity} @ {order.limit_price}"
                )
                return order

            if order.action == TradeAction.BUY:
                return await self._place_buy_order(order)

            return await self._place_sell_order(order)

        except Exception as error:
            if order.status in {
                OrderStatus.PENDING,
                OrderStatus.SUBMITTED,
            }:
                OrderRules.mark_failed(order, str(error))

            try:
                await self._save_order(order)

            except Exception:
                raise error

            self._logger.error(f"{MockLogMessage.ORDER_FAILED} {order.stock_id}: {error}")
            return order

    async def cancel_order(
        self,
        order_id: UUID,
    ) -> Order | None:
        await self._ensure_account()

        async with self._db.get_session() as session:
            result = await session.execute(
                select(MockOrder).where(
                    col(MockOrder.id) == order_id,
                    col(MockOrder.account_id) == self._account_id,
                )
            )
            order = result.scalar_one_or_none()

            if order is None or order.status != OrderStatus.SUBMITTED:
                return None

            OrderRules.mark_cancelled(order)

            await session.commit()
            await session.refresh(order)

            self._logger.info(f"{MockLogMessage.ORDER_CANCELLED} {order.id}")

            return Order.model_validate(order)

    async def get_positions(self) -> list[Position]:
        await self._ensure_account()

        async with self._db.get_session() as session:
            result = await session.execute(select(MockPosition).where(col(MockPosition.account_id) == self._account_id))
            rows = result.scalars().all()

        return [
            Position(
                stock_id=row.stock_id,
                quantity=row.quantity,
                average_cost=row.average_cost,
                opened_at=row.opened_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def get_cash_balance(self) -> float:
        await self._ensure_account()

        async with self._db.get_session() as session:
            cash = await self._get_cash(session)

            if cash is None:
                return self._initial_cash

            return cash.current_cash

    async def _place_buy_order(
        self,
        order: Order,
    ) -> Order:
        execution_price = order.limit_price

        if execution_price is None:
            raise ValueError("LIMIT order requires limit_price")

        base_value = execution_price * order.quantity
        market_rules = self._config.market

        fee = max(
            market_rules.min_fee,
            int(base_value * market_rules.fee_rate),
        )
        total_cost = base_value + fee

        async with self._db.get_session() as session:
            cash = await self._get_cash(session)

            if cash is None:
                raise RuntimeError("Mock account was not initialized")

            if cash.current_cash < total_cost:
                OrderRules.mark_rejected(
                    order,
                    MockRejectReason.INSUFFICIENT_CASH,
                )
                await self._save_order_in_session(
                    session,
                    order,
                )

                self._logger.warning(f"{MockLogMessage.ORDER_REJECTED} {order.action} {order.stock_id}: {order.reason}")
                return order

            position = await self._get_position(
                session,
                order.stock_id,
            )

            if position is None:
                session.add(
                    MockPosition(
                        account_id=self._account_id,
                        stock_id=order.stock_id,
                        quantity=order.quantity,
                        average_cost=execution_price,
                    )
                )

            else:
                position.average_cost = self._calculate_average_cost(
                    current_quantity=position.quantity,
                    current_average_cost=(position.average_cost),
                    added_quantity=order.quantity,
                    added_price=execution_price,
                )
                position.quantity += order.quantity
                position.updated_at = self._now()

            cash.current_cash -= total_cost
            cash.updated_at = self._now()

            OrderRules.mark_filled(
                order,
                execution_price,
            )
            await self._save_order_in_session(
                session,
                order,
            )

            self._logger.success(
                f"{MockLogMessage.ORDER_FILLED} "
                f"BUY {order.stock_id} x {order.quantity} "
                f"(Price: {execution_price}, "
                f"Fee: {fee}, Total: {total_cost})"
            )

            return order

    async def _place_sell_order(
        self,
        order: Order,
    ) -> Order:
        execution_price = order.limit_price

        if execution_price is None:
            raise ValueError("LIMIT order requires limit_price")

        base_value = execution_price * order.quantity
        market_rules = self._config.market

        fee = max(
            market_rules.min_fee,
            int(base_value * market_rules.fee_rate),
        )
        tax = int(base_value * market_rules.tax_rate)
        net_revenue = base_value - fee - tax

        async with self._db.get_session() as session:
            cash = await self._get_cash(session)
            position = await self._get_position(
                session,
                order.stock_id,
            )

            if cash is None:
                raise RuntimeError("Mock account was not initialized")

            if position is None:
                OrderRules.mark_rejected(
                    order,
                    MockRejectReason.POSITION_NOT_FOUND,
                )
                await self._save_order_in_session(
                    session,
                    order,
                )

                self._logger.warning(f"{MockLogMessage.ORDER_REJECTED} {order.action} {order.stock_id}: {order.reason}")
                return order

            if position.quantity < order.quantity:
                OrderRules.mark_rejected(
                    order,
                    MockRejectReason.INSUFFICIENT_POSITION,
                )
                await self._save_order_in_session(
                    session,
                    order,
                )

                self._logger.warning(f"{MockLogMessage.ORDER_REJECTED} {order.action} {order.stock_id}: {order.reason}")
                return order

            remaining_quantity = position.quantity - order.quantity

            if remaining_quantity == 0:
                await session.delete(position)

            else:
                position.quantity = remaining_quantity
                position.updated_at = self._now()

            cash.current_cash += net_revenue
            cash.updated_at = self._now()

            OrderRules.mark_filled(
                order,
                execution_price,
            )
            await self._save_order_in_session(
                session,
                order,
            )

            self._logger.success(
                f"{MockLogMessage.ORDER_FILLED} "
                f"SELL {order.stock_id} x {order.quantity} "
                f"(Price: {execution_price}, "
                f"Fee: {fee}, Tax: {tax}, "
                f"Net: {net_revenue})"
            )

            return order

    async def _save_order(
        self,
        order: Order,
    ) -> None:
        async with self._db.get_session() as session:
            await self._save_order_in_session(
                session,
                order,
            )

    async def _save_order_in_session(
        self,
        session,
        order: Order,
    ) -> None:
        session.add(
            MockOrder(
                **order.model_dump(),
                account_id=self._account_id,
            )
        )
        await session.commit()

    async def _ensure_account(self) -> None:
        async with self._db.get_session() as session:
            cash = await self._get_cash(session)

            if cash is not None:
                return

            session.add(
                MockCash(
                    account_id=self._account_id,
                    current_cash=self._initial_cash,
                    initial_cash=self._initial_cash,
                )
            )
            await session.commit()

            self._logger.info(MockLogMessage.ACCOUNT_SEEDED)

    async def _get_cash(
        self,
        session,
    ) -> MockCash | None:
        result = await session.execute(select(MockCash).where(col(MockCash.account_id) == self._account_id))
        return result.scalar_one_or_none()

    async def _get_position(
        self,
        session,
        stock_id: str,
    ) -> MockPosition | None:
        result = await session.execute(
            select(MockPosition).where(
                col(MockPosition.account_id) == self._account_id,
                col(MockPosition.stock_id) == stock_id,
            )
        )
        return result.scalar_one_or_none()

    def _calculate_average_cost(
        self,
        *,
        current_quantity: int,
        current_average_cost: float,
        added_quantity: int,
        added_price: float,
    ) -> float:
        current_value = current_quantity * current_average_cost
        added_value = added_quantity * added_price
        total_quantity = current_quantity + added_quantity

        return (current_value + added_value) / total_quantity

    def _now(self) -> datetime:
        return datetime.now()
