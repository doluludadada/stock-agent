from uuid import UUID

from sqlalchemy import select
from sqlmodel import col

from a_domain.model.trading.account import Account
from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
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
            order.validate_submission()

        except ValueError as error:
            order.reject(str(error))
            await self._save_order(order)

            self._logger.warning(f"{MockLogMessage.ORDER_REJECTED} {order.action} {order.stock_id}: {order.reason}")
            return order

        try:
            if order.order_type != OrderType.LIMIT:
                order.reject(MockRejectReason.UNSUPPORTED_ORDER_TYPE)
                await self._save_order(order)

                self._logger.warning(f"{MockLogMessage.ORDER_REJECTED} {order.action} {order.stock_id}: {order.reason}")
                return order

            if order.time_in_force == TimeInForce.ROD:
                order.submit()
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
                order.fail(str(error))

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

            cancelled_order = Order.model_validate(order)
            cancelled_order.cancel()

            order.status = cancelled_order.status
            order.reason = cancelled_order.reason
            order.updated_at = cancelled_order.updated_at

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

            position = await self._get_position(
                session,
                order.stock_id,
            )
            account = self._account_from(
                cash,
                position,
            )

            if not account.can_afford(total_cost):
                order.reject(MockRejectReason.INSUFFICIENT_CASH)
                await self._save_order_in_session(
                    session,
                    order,
                )

                self._logger.warning(f"{MockLogMessage.ORDER_REJECTED} {order.action} {order.stock_id}: {order.reason}")
                return order

            domain_position = account.buy(
                order.stock_id,
                order.quantity,
                execution_price,
                total_cost,
            )

            if position is None:
                session.add(self._new_position(domain_position))

            else:
                self._sync_position(
                    position,
                    domain_position,
                )

            self._sync_cash(
                cash,
                account,
            )

            order.fill(execution_price)
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

            account = self._account_from(
                cash,
                position,
            )
            domain_position = account.position_for(order.stock_id)

            if domain_position is None:
                order.reject(MockRejectReason.POSITION_NOT_FOUND)
                await self._save_order_in_session(
                    session,
                    order,
                )

                self._logger.warning(f"{MockLogMessage.ORDER_REJECTED} {order.action} {order.stock_id}: {order.reason}")
                return order

            if not domain_position.can_cover(order.quantity):
                order.reject(MockRejectReason.INSUFFICIENT_POSITION)
                await self._save_order_in_session(
                    session,
                    order,
                )

                self._logger.warning(f"{MockLogMessage.ORDER_REJECTED} {order.action} {order.stock_id}: {order.reason}")
                return order

            remaining_quantity = account.sell(
                order.stock_id,
                order.quantity,
                net_revenue,
            )

            if remaining_quantity == 0:
                await session.delete(position)

            else:
                self._sync_position(
                    position,
                    domain_position,
                )

            self._sync_cash(
                cash,
                account,
            )

            order.fill(execution_price)
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

    def _account_from(
        self,
        cash: MockCash,
        position: MockPosition | None,
    ) -> Account:
        positions = [] if position is None else [self._to_position(position)]

        return Account(
            cash=cash.current_cash,
            positions=positions,
        )

    def _to_position(
        self,
        position: MockPosition,
    ) -> Position:
        return Position(
            stock_id=position.stock_id,
            quantity=position.quantity,
            average_cost=position.average_cost,
            opened_at=position.opened_at,
            updated_at=position.updated_at,
        )

    def _new_position(
        self,
        position: Position,
    ) -> MockPosition:
        return MockPosition(
            account_id=self._account_id,
            stock_id=position.stock_id,
            quantity=position.quantity,
            average_cost=position.average_cost,
        )

    def _sync_position(
        self,
        row: MockPosition,
        position: Position,
    ) -> None:
        row.quantity = position.quantity
        row.average_cost = position.average_cost
        row.updated_at = position.updated_at

    def _sync_cash(
        self,
        row: MockCash,
        account: Account,
    ) -> None:
        row.current_cash = account.cash
        row.updated_at = account.updated_at
