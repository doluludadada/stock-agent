from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlmodel import col

from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import OrderStatus, TradeAction
from b_application.schemas.config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.mock_trading_dto import MockCash, MockOrder, MockPosition
from c_infrastructure.trading.mock.constants import MockLogMessage, MockRejectReason


class MockExecutionProvider(IExecutionProvider):
    """
    DEV / TEST fake broker with database persistence.

    State is persisted in mock_cash, mock_positions, and mock_orders.
    Includes universal market friction costs (fees and taxes).
    """

    def __init__(
        self,
        db: DatabaseConnector,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._db = db
        self._config = config
        self._logger = logger
        self._account_id = config.mock_trading.account_id
        self._initial_cash = config.mock_trading.initial_cash

    async def place_order(self, order: Order) -> str:
        await self._ensure_account()

        if order.quantity <= 0:
            return await self._save_rejected_order(order, MockRejectReason.INVALID_QUANTITY)

        if order.price is None or order.price <= 0:
            return await self._save_rejected_order(order, MockRejectReason.INVALID_PRICE)

        if order.action == TradeAction.BUY:
            return await self._place_buy_order(order)

        if order.action == TradeAction.SELL:
            return await self._place_sell_order(order)

        return await self._save_rejected_order(order, MockRejectReason.UNSUPPORTED_ACTION)

    async def cancel_order(self, order_id: str) -> bool:
        await self._ensure_account()

        try:
            parsed_order_id = UUID(order_id)
        except ValueError:
            return False

        async with self._db.get_session() as session:
            result = await session.execute(
                select(MockOrder).where(
                    col(MockOrder.id) == parsed_order_id,
                    col(MockOrder.account_id) == self._account_id,
                )
            )
            order = result.scalar_one_or_none()

            if order is None:
                return False

            if order.status != OrderStatus.PENDING:
                return False

            order.status = OrderStatus.CANCELLED
            order.updated_at = self._now()

            await session.commit()
            return True

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

    async def _place_buy_order(self, order: Order) -> str:
        price = self._require_price(order)
        base_value = price * order.quantity

        # Calculate universal friction costs
        trading_rules = self._config.market
        fee = max(trading_rules.min_fee, int(base_value * trading_rules.fee_rate))
        total_cost = base_value + fee

        async with self._db.get_session() as session:
            cash = await self._get_cash(session)

            if cash is None:
                raise RuntimeError("Mock account was not initialized.")

            if cash.current_cash < total_cost:
                return await self._save_rejected_order_in_session(
                    session=session,
                    order=order,
                    reason=MockRejectReason.INSUFFICIENT_CASH,
                )

            position = await self._get_position(session, order.stock_id)

            if position is None:
                session.add(
                    MockPosition(
                        account_id=self._account_id,
                        stock_id=order.stock_id,
                        quantity=order.quantity,
                        average_cost=price,
                    )
                )
            else:
                position.average_cost = self._calculate_average_cost(
                    current_quantity=position.quantity,
                    current_average_cost=position.average_cost,
                    added_quantity=order.quantity,
                    added_price=price,
                )
                position.quantity += order.quantity
                position.updated_at = self._now()

            cash.current_cash -= total_cost
            cash.updated_at = self._now()

            mock_order = self._create_order_row(
                order=order,
                status=OrderStatus.FILLED,
                reason=None,
            )
            session.add(mock_order)

            await session.commit()

            self._logger.success(
                f"{MockLogMessage.ORDER_FILLED} BUY {order.stock_id} x {order.quantity} "
                f"(Price: {price}, Fee: {fee}, Total: {total_cost})"
            )

            return str(mock_order.id)

    async def _place_sell_order(self, order: Order) -> str:
        price = self._require_price(order)
        base_value = price * order.quantity

        # Calculate universal friction costs (Fees + Tax)
        market_rules = self._config.market
        fee = max(market_rules.min_fee, int(base_value * market_rules.fee_rate))
        tax = int(base_value * market_rules.tax_rate)
        net_revenue = base_value - fee - tax

        async with self._db.get_session() as session:
            cash = await self._get_cash(session)
            position = await self._get_position(session, order.stock_id)

            if cash is None:
                raise RuntimeError("Mock account was not initialized.")

            if position is None:
                return await self._save_rejected_order_in_session(
                    session=session,
                    order=order,
                    reason=MockRejectReason.POSITION_NOT_FOUND,
                )

            if position.quantity < order.quantity:
                return await self._save_rejected_order_in_session(
                    session=session,
                    order=order,
                    reason=MockRejectReason.INSUFFICIENT_POSITION,
                )

            remaining_quantity = position.quantity - order.quantity

            if remaining_quantity == 0:
                await session.delete(position)
            else:
                position.quantity = remaining_quantity
                position.updated_at = self._now()

            # 增加扣除手續費及稅後的淨收入
            cash.current_cash += net_revenue
            cash.updated_at = self._now()

            mock_order = self._create_order_row(
                order=order,
                status=OrderStatus.FILLED,
                reason=None,
            )
            session.add(mock_order)

            await session.commit()

            self._logger.success(
                f"{MockLogMessage.ORDER_FILLED} SELL {order.stock_id} x {order.quantity} "
                f"(Price: {price}, Fee: {fee}, Tax: {tax}, Net: {net_revenue})"
            )

            return str(mock_order.id)

    async def _save_rejected_order(self, order: Order, reason: str) -> str:
        async with self._db.get_session() as session:
            return await self._save_rejected_order_in_session(
                session=session,
                order=order,
                reason=reason,
            )

    async def _save_rejected_order_in_session(self, session, order: Order, reason: str) -> str:
        mock_order = self._create_order_row(
            order=order,
            status=OrderStatus.REJECTED,
            reason=reason,
        )
        session.add(mock_order)

        await session.commit()

        self._logger.warning(f"{MockLogMessage.ORDER_REJECTED} {order.action} {order.stock_id}: {reason}")

        return str(mock_order.id)

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

    async def _get_cash(self, session) -> MockCash | None:
        result = await session.execute(select(MockCash).where(col(MockCash.account_id) == self._account_id))
        return result.scalar_one_or_none()

    async def _get_position(self, session, stock_id: str) -> MockPosition | None:
        result = await session.execute(
            select(MockPosition).where(
                col(MockPosition.account_id) == self._account_id,
                col(MockPosition.stock_id) == stock_id,
            )
        )
        return result.scalar_one_or_none()

    def _create_order_row(
        self,
        *,
        order: Order,
        status: OrderStatus,
        reason: str | None,
    ) -> MockOrder:
        return MockOrder(
            account_id=self._account_id,
            stock_id=order.stock_id,
            action=order.action,
            order_type=order.order_type,
            price=order.price or 0,
            quantity=order.quantity,
            status=status,
            reason=reason,
        )

    def _require_price(self, order: Order) -> float:
        if order.price is None:
            raise ValueError(MockRejectReason.INVALID_PRICE)

        return order.price

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
        return datetime.now(timezone.utc)
