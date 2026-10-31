from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from a_domain.model.trading.account import Account
from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import OrderStatus, OrderType, RejectReason, TimeInForce, TradeAction
from b_application.config.app_config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.mock_trading_dto import MockCash, MockPosition
from c_infrastructure.trading.mock.constants import MockLogMessage


class MockExecutionProvider(IExecutionProvider):
    """
    Database-backed broker simulator for DEV and TEST.

    Its book is the account only: cash (mock_cash) and positions (mock_positions). It keeps no
    order table. The app records every order it sends in the `orders` table, the same audit trail
    a live provider's results land in, and the mock never holds a working order (see ROD below),
    so it has no order state of its own to keep.

    Fill model: there is no market feed. The limit price is taken as the market price
    (OrderExecution prices orders from a fresh quote), and the simulated market fills at most
    `mock_trading.max_fill_quantity` shares per order at that price (unset: any quantity).
    Fees and tax come from TradingCostRule.

    Before acceptance (REJECTED): a MARKET order, ROD, a BUY without cash for the whole quantity plus
    fee, a SELL of shares the account does not hold.
    After acceptance, by time in force:
    - IOC fills what the market can take now and cancels the remainder.
    - FOK fills the whole quantity now, or cancels all of it.
    - ROD is rejected: its remainder would stay working until the close, but nothing could ever
      fill it (no feed) and nothing in the app reconciles working orders.
    An unexpected exception FAILS the order and leaves the book untouched.
    """

    def __init__(self, db: DatabaseConnector, config: AppConfig, logger: ILoggingProvider) -> None:
        self._db = db
        self._logger = logger
        self._account_id = config.mock_trading.account_id
        self._initial_cash = config.mock_trading.initial_cash
        self._max_fill_quantity = config.mock_trading.max_fill_quantity
        self._cost_rule = config.market.cost_rule()

    async def place_order(self, order: Order) -> Order:
        now = datetime.now(UTC)

        try:
            await self._ensure_account()

            async with self._db.get_session() as session:
                cash = await self._get_cash(session)
                position_row = await self._get_position(session, order.stock_id)
                account = Account(cash=cash.current_cash, positions=[] if position_row is None else [self._to_position(position_row)])

                refusal = self._refusal(order, account)

                if refusal is not None:
                    order.reject(*refusal, now=now)
                    self._logger.warning(f"{MockLogMessage.ORDER_REJECTED} {order.action} {order.stock_id}: {order.reason}")
                    return order

                order.submit(now=now)
                await self._execute(session, order, account, cash, position_row, now)

        except Exception as error:
            if order.status not in {OrderStatus.PENDING, OrderStatus.SUBMITTED}:
                raise

            order.fail(f"{type(error).__name__}: {error}", now=now)
            self._logger.error(f"{MockLogMessage.ORDER_FAILED} {order.stock_id}: {order.reason}")

        return order

    async def get_account(self) -> Account:
        await self._ensure_account()

        async with self._db.get_session() as session:
            cash = await self._get_cash(session)
            result = await session.execute(select(MockPosition).where(col(MockPosition.account_id) == self._account_id))
            positions = [self._to_position(row) for row in result.scalars().all()]

        return Account(account_id=self._account_id, cash=cash.current_cash, positions=positions)

    def _refusal(self, order: Order, account: Account) -> tuple[RejectReason, str] | None:
        if order.order_type != OrderType.LIMIT or order.limit_price is None:
            return RejectReason.UNSUPPORTED_ORDER_TYPE, "the mock fills LIMIT orders only"

        if order.time_in_force == TimeInForce.ROD:
            return (
                RejectReason.UNSUPPORTED_TIME_IN_FORCE,
                "the mock accepts IOC and FOK only; a ROD remainder would stay working forever",
            )

        return account.refusal_for(order, self._cost_rule)

    def _fill_quantity(self, order: Order) -> int:
        available = order.quantity if self._max_fill_quantity is None else min(order.quantity, self._max_fill_quantity)

        if order.time_in_force == TimeInForce.FOK and available < order.quantity:
            return 0

        return available

    async def _execute(
        self, session: AsyncSession, order: Order, account: Account, cash: MockCash, position_row: MockPosition | None, now: datetime
    ) -> None:
        quantity = self._fill_quantity(order)
        price = order.limit_price

        if quantity > 0 and price is not None:
            cost = self._cost_rule.cost_of(order.action, order.stock_id, price, quantity)
            realized_pnl = None

            if order.action == TradeAction.BUY:
                account.buy(order.stock_id, quantity, price=price, total_cost=-cost.net)
            else:
                position = account.position_for(order.stock_id)
                realized_pnl = position.profit_on_sale(quantity, cost.net) if position else None
                account.sell(order.stock_id, quantity, cash_delta=cost.net)

            await self._save_book(session, account, cash, position_row, order.stock_id, now)
            order.fill(quantity, price, cost, realized_pnl, now=now)

            self._logger.success(
                f"{MockLogMessage.ORDER_FILLED} {order.action} {order.stock_id} x {quantity} @ {price} "
                f"(fee {cost.fee}, tax {cost.tax}, cash {cost.net:+,.0f})"
            )

        if order.remaining_quantity > 0:
            order.cancel(
                f"{order.time_in_force.name} unfilled: the market filled {order.filled_quantity} of {order.quantity}", now=now
            )
            self._logger.info(f"{MockLogMessage.ORDER_CANCELLED} {order.stock_id}: {order.reason}")

    async def _save_book(
        self, session: AsyncSession, account: Account, cash: MockCash, position_row: MockPosition | None, stock_id: str, now: datetime
    ) -> None:
        position = account.position_for(stock_id)

        if position is None and position_row is not None:
            await session.delete(position_row)

        elif position is not None and position_row is None:
            session.add(
                MockPosition(
                    account_id=self._account_id, stock_id=stock_id, quantity=position.quantity, average_cost=position.average_cost
                )
            )

        elif position is not None and position_row is not None:
            position_row.quantity = position.quantity
            position_row.average_cost = position.average_cost
            position_row.updated_at = now

        cash.current_cash = account.cash
        cash.updated_at = now
        await session.commit()

    async def _ensure_account(self) -> None:
        async with self._db.get_session() as session:
            result = await session.execute(select(MockCash).where(col(MockCash.account_id) == self._account_id))

            if result.scalar_one_or_none() is not None:
                return

            session.add(MockCash(account_id=self._account_id, current_cash=self._initial_cash, initial_cash=self._initial_cash))
            await session.commit()

            self._logger.info(MockLogMessage.ACCOUNT_SEEDED)

    async def _get_cash(self, session: AsyncSession) -> MockCash:
        result = await session.execute(select(MockCash).where(col(MockCash.account_id) == self._account_id))
        return result.scalar_one()

    async def _get_position(self, session: AsyncSession, stock_id: str) -> MockPosition | None:
        result = await session.execute(
            select(MockPosition).where(col(MockPosition.account_id) == self._account_id, col(MockPosition.stock_id) == stock_id)
        )
        return result.scalar_one_or_none()

    def _to_position(self, row: MockPosition) -> Position:
        return Position(stock_id=row.stock_id, quantity=row.quantity, average_cost=row.average_cost, opened_at=row.opened_at)
