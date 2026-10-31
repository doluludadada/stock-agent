from datetime import UTC, datetime
from typing import override

from sqlmodel import col, select

from a_domain.model.trading.account import Account
from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import ISimulatedExecutionProvider
from a_domain.rules.trading.execution import FillRule
from a_domain.types.enums import OrderStatus, OrderType, RejectReason, TimeInForce, TradeAction
from b_application.config.app_config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.mock_trading_dto import MockCash, MockPosition


class MockExecutionProvider(ISimulatedExecutionProvider):
    """
    Database-backed broker simulator for DEV and TEST.

    Its book is the account only: cash (mock_cash) and positions (mock_positions). It keeps no
    order table. The app records every order it sends in the `orders` table, the same audit trail
    a live provider's results land in, and the mock never holds a working order (see ROD below),
    so it has no order state of its own to keep. connect seeds the book, and every account read
    calls it, so the book is seeded on first use.

    Fill model: there is no market feed. The limit price is taken as the market price
    (OrderExecution prices orders from a fresh quote), and the simulated market fills at most
    `mock_trading.max_fill_quantity` shares per order at that price (unset: any quantity).
    Fees, tax and realized PnL come from FillRule.

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
        self._fill_rule = FillRule(cost_rule=self._cost_rule)

    @override
    async def connect(self) -> None:
        """Seeds the book with mock_trading.initial_cash the first time. Later calls find the account and change nothing."""
        async with self._db.get_session() as session:
            if await session.get(MockCash, self._account_id) is not None:
                return

            session.add(MockCash(account_id=self._account_id, current_cash=self._initial_cash, initial_cash=self._initial_cash))
            await session.commit()

            self._logger.info("Mock account seeded.")

    @override
    async def place_order(self, order: Order) -> Order:
        now = datetime.now(UTC)

        try:
            account = await self.get_account()
            refusal = self.refusal_for(order, account)

            if refusal is not None:
                order.reject(*refusal, now=now)
                self._logger.warning(f"Mock order rejected. {order.action} {order.stock_id}: {order.reason}")
                return order

            order.submit(now=now)
            await self.fill(order, account, now)

            if order.remaining_quantity > 0:
                order.cancel(
                    f"{order.time_in_force.name} unfilled: the market filled {order.filled_quantity} of {order.quantity}", now=now
                )
                self._logger.info(f"Mock order cancelled. {order.stock_id}: {order.reason}")

        except Exception as error:
            if order.status not in {OrderStatus.PENDING, OrderStatus.SUBMITTED}:
                raise

            order.fail(f"{type(error).__name__}: {error}", now=now)
            self._logger.error(f"Mock order failed. {order.stock_id}: {order.reason}")

        return order

    @override
    async def get_account(self) -> Account:
        await self.connect()

        async with self._db.get_session() as session:
            cash = await session.get_one(MockCash, self._account_id)
            result = await session.execute(select(MockPosition).where(col(MockPosition.account_id) == self._account_id))
            positions = [
                Position(stock_id=row.stock_id, quantity=row.quantity, average_cost=row.average_cost, opened_at=row.opened_at)
                for row in result.scalars().all()
            ]

        return Account(account_id=self._account_id, cash=cash.current_cash, positions=positions)

    @override
    def refusal_for(self, order: Order, account: Account) -> tuple[RejectReason, str] | None:
        if order.order_type != OrderType.LIMIT or order.limit_price is None:
            return RejectReason.UNSUPPORTED_ORDER_TYPE, "the mock fills LIMIT orders only"

        if order.time_in_force == TimeInForce.ROD:
            return (
                RejectReason.UNSUPPORTED_TIME_IN_FORCE,
                "the mock accepts IOC and FOK only; a ROD remainder would stay working forever",
            )

        return account.refusal_for(order, self._cost_rule)

    @override
    async def fill(self, order: Order, account: Account, now: datetime) -> None:
        available = order.quantity if self._max_fill_quantity is None else min(order.quantity, self._max_fill_quantity)
        quantity = 0 if order.time_in_force == TimeInForce.FOK and available < order.quantity else available
        price = order.limit_price

        if quantity == 0 or price is None:
            return

        cost, realized_pnl = self._fill_rule.apply(order, quantity, price, account.position_for(order.stock_id), now=now)

        if order.action == TradeAction.BUY:
            account.buy(order.stock_id, quantity, price=price, total_cost=-cost.net)
        else:
            account.sell(order.stock_id, quantity, cash_delta=cost.net)

        await self.save_account(account, now)
        order.fill(quantity, price, cost, realized_pnl, now=now)
        self._logger.success(
            f"Mock order filled. {order.action} {order.stock_id} x {quantity} @ {price} "
            f"(fee {cost.fee}, tax {cost.tax}, cash {cost.net:+,.0f})"
        )

    @override
    async def save_account(self, account: Account, now: datetime) -> None:
        """Deletes the rows of positions no longer held, adds the new ones, and updates the ones whose shares or cost changed."""
        held = {position.stock_id: position for position in account.positions}

        async with self._db.get_session() as session:
            cash = await session.get_one(MockCash, self._account_id)
            result = await session.execute(select(MockPosition).where(col(MockPosition.account_id) == self._account_id))
            rows = {row.stock_id: row for row in result.scalars().all()}

            for stock_id in rows.keys() - held.keys():
                await session.delete(rows[stock_id])

            for stock_id, position in held.items():
                row = rows.get(stock_id)

                if row is None:
                    session.add(
                        MockPosition(
                            account_id=self._account_id,
                            stock_id=stock_id,
                            quantity=position.quantity,
                            average_cost=position.average_cost,
                        )
                    )

                elif (row.quantity, row.average_cost) != (position.quantity, position.average_cost):
                    row.quantity, row.average_cost, row.updated_at = position.quantity, position.average_cost, now

            cash.current_cash = account.cash
            cash.updated_at = now
            await session.commit()
