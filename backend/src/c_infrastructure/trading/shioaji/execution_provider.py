import asyncio
import math
from collections.abc import Mapping
from typing import Self

from shioaji import Shioaji
from shioaji.constant import Action, OrderType as BrokerTimeInForce, Status, StockOrderCond, StockOrderLot, StockPriceType, Unit
from shioaji.contracts import Stock as StockContract
from shioaji.order import Order as BrokerOrder, Trade

from a_domain.model.trading.account import Account
from a_domain.model.trading.order import ORDER_TRANSITIONS, Order
from a_domain.model.trading.position import Position
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import OrderStatus, OrderType, RejectReason, TimeInForce, TradeAction
from b_application.schemas.config import AppConfig, ShioajiConfig

SHARES_PER_UNIT: Mapping[StockOrderLot, int] = {StockOrderLot.Common: 1000, StockOrderLot.IntradayOdd: 1}
"""Shares in one unit of a Shioaji order quantity: a board lot is 1000 shares, an intraday odd-lot order counts shares."""

BROKER_ACTION: Mapping[TradeAction, Action] = {TradeAction.BUY: Action.Buy, TradeAction.SELL: Action.Sell}

BROKER_TIME_IN_FORCE: Mapping[TimeInForce, BrokerTimeInForce] = {
    TimeInForce.IOC: BrokerTimeInForce.IOC,
    TimeInForce.FOK: BrokerTimeInForce.FOK,
}
"""ROD is not sent: its remainder would keep working after place_order returns, and the app tracks no working orders."""

ORDER_STATUS: Mapping[Status, OrderStatus] = {
    Status.PendingSubmit: OrderStatus.PENDING,
    Status.PreSubmitted: OrderStatus.SUBMITTED,
    Status.Submitted: OrderStatus.SUBMITTED,
    Status.PartFilled: OrderStatus.SUBMITTED,
    Status.Filled: OrderStatus.FILLED,
    Status.Cancelled: OrderStatus.CANCELLED,
    Status.Failed: OrderStatus.REJECTED,
    Status.Inactive: OrderStatus.FAILED,
}
"""
What each Shioaji status means in the domain order lifecycle (ORDER_TRANSITIONS).

- PendingSubmit: on its way, not acknowledged yet.
- PreSubmitted: a reservation the broker holds until the session opens, so it is working.
- PartFilled: part executed, the rest still working (SUBMITTED -> SUBMITTED).
- Cancelled: stopped with the rest unfilled: an IOC remainder, a FOK kill, or the adapter's cancel.
- Failed: the broker or the exchange refused it.
- Inactive: done, with no documented meaning, so it is reported as an error for a human to look at.
"""


def lot_parts(quantity: int) -> list[tuple[StockOrderLot, int]]:
    """
    Splits a quantity in shares into what Shioaji can send: the whole 1000-share lots as one board-lot order
    and the remaining shares as one intraday odd-lot order. 2500 shares are 2 lots plus 500 odd shares.
    """
    lots, odd_shares = divmod(quantity, SHARES_PER_UNIT[StockOrderLot.Common])

    return [(lot, count) for lot, count in ((StockOrderLot.Common, lots), (StockOrderLot.IntradayOdd, odd_shares)) if count]


def is_done(trade: Trade) -> bool:
    return not ORDER_TRANSITIONS[ORDER_STATUS[trade.status.status]]


def ordered_shares(trade: Trade) -> int:
    return trade.order.quantity * SHARES_PER_UNIT[trade.order.order_lot]


def dealt_units(trade: Trade) -> int:
    return sum(deal.quantity for deal in trade.status.deals or [])


def dealt_shares(trade: Trade) -> int:
    return dealt_units(trade) * SHARES_PER_UNIT[trade.order.order_lot]


def fill_price(trade: Trade) -> float:
    """The deals' volume-weighted price. Deals at one price give exactly that price, which a float average may not."""
    deals = trade.status.deals or []
    prices = {deal.price for deal in deals}

    return prices.pop() if len(prices) == 1 else math.fsum(deal.price * deal.quantity for deal in deals) / dealt_units(trade)


def describe(trade: Trade) -> str:
    unit = "lots" if trade.order.order_lot == StockOrderLot.Common else "shares"
    text = (
        f"{trade.order.order_lot.value} {trade.order.quantity} {unit} {trade.status.status.value}, dealt {dealt_shares(trade)} shares"
    )

    return f"{text} ({trade.status.msg})" if trade.status.msg else text


def log_in(client: Shioaji, credentials: ShioajiConfig) -> None:
    """Logs in, then in production activates the CA certificate that signs orders. Blocking; raises saying what failed."""
    client.login(
        api_key=credentials.api_key.get_secret_value(), secret_key=credentials.secret_key.get_secret_value(), subscribe_trade=False
    )
    account = client.stock_account

    if account is None:
        raise RuntimeError("the login returned no stock account")

    if credentials.simulation:
        return

    activated = client.activate_ca(
        ca_path=credentials.ca_path,
        ca_passwd=credentials.ca_password.get_secret_value(),
        person_id=credentials.person_id.get_secret_value(),
    )

    if not activated:
        raise RuntimeError(f"the CA certificate at {credentials.ca_path} was not activated")

    if not account.signed:
        raise RuntimeError(f"stock account {account.account_id} has not signed Shioaji's API trading agreement")


class ShioajiExecutionProvider(IExecutionProvider):
    """
    The Sinopac broker through the Shioaji client, simulation or production as `shioaji.simulation` says.

    The client is synchronous, so every call runs in a worker thread. Quantities are shares in the domain:
    lot_parts sends the whole lots as a board-lot order and the rest as an intraday odd-lot order, both
    LIMIT at the order's limit price with its time in force (IOC or FOK). FOK is refused for a quantity
    that needs both, because the two broker orders cannot fill or fail together.

    Before sending, the account must cover the order (Account.refusal_for): the broker checks a BUY against
    the trading limit, not the cash, so without this check a BUY could exceed the cash and default at
    settlement. Cash is the bank balance, minus the settlement payments still due (T to T+2), minus every BUY
    the broker lists as dealt today with its fee. A purchase the broker already counts in its settlements is
    subtracted twice, and pending receipts from sales are not counted, so cash can be understated, never
    overstated, as long as the broker reports payments as negative settlement amounts.

    After sending, the adapter refreshes each broker order until ORDER_STATUS says it is done. One still
    working after the polls is cancelled and refreshed again; one still working after that FAILS the
    domain order with a reason that says to check the broker. If place_order itself raises (a timeout),
    the adapter looks for the order by its tag before giving up. Each broker order carries the tag
    `custom_field = order.id.hex[:5] + part index`, so a human can match a broker order to its journal row.
    After each update_status the adapter reads the order back from list_trades by that tag, so it does not
    depend on update_status changing the Trade object place_order returned.

    Executions come from the broker's deals: one Order.fill per broker order at its volume-weighted price.
    Fee and tax are TradingCostRule's, which may differ from the broker's discounted fee.
    """

    def __init__(
        self, client: Shioaji, config: AppConfig, logger: ILoggingProvider, poll_interval_seconds: float = 0.5, max_polls: int = 10
    ) -> None:
        self._client = client
        self._cost_rule = config.market.cost_rule()
        self._logger = logger
        self._poll_interval_seconds = poll_interval_seconds
        self._max_polls = max_polls

    @classmethod
    async def connect(cls, config: AppConfig, logger: ILoggingProvider) -> Self:
        client = Shioaji(simulation=config.shioaji.simulation)
        await asyncio.to_thread(log_in, client, config.shioaji)

        return cls(client=client, config=config, logger=logger)

    async def get_account(self) -> Account:
        return await asyncio.to_thread(self._read_account)

    async def place_order(self, order: Order) -> Order:
        try:
            account = await asyncio.to_thread(self._read_account)
            contract = await asyncio.to_thread(lambda: self._client.Contracts.Stocks[order.stock_id])
            refusal = self._refusal(order, account, contract)

            if refusal is not None:
                order.reject(*refusal)
                self._logger.warning(f"Shioaji order not sent: {order.action} {order.stock_id}: {order.reason}")
                return order

            trades: list[Trade] = []

            for index, (lot, count) in enumerate(lot_parts(order.quantity)):
                trade = await self._send(contract, self._broker_order(order, lot, count, index))
                self._record_fill(order, trade, account.position_for(order.stock_id))
                trades.append(trade)

                if not is_done(trade):
                    break

            self._close(order, trades)

        except Exception as error:
            if order.status not in {OrderStatus.PENDING, OrderStatus.SUBMITTED}:
                raise

            order.fail(f"{type(error).__name__}: {error}")
            self._logger.error(f"Shioaji order failed: {order.stock_id}: {order.reason}")

        return order

    def _read_account(self) -> Account:
        stock_account = self._client.stock_account
        balance = self._client.account_balance()

        if balance.errmsg:
            raise RuntimeError(f"Shioaji account balance unavailable: {balance.errmsg}")

        payments_due = math.fsum(min(settlement.amount, 0) for settlement in self._client.settlements(stock_account))
        self._client.update_status(account=stock_account)
        bought_today = math.fsum(
            -self._cost_rule.cost_of(TradeAction.BUY, fill_price(trade), dealt_shares(trade)).net
            for trade in self._client.list_trades()
            if trade.order.account == stock_account and trade.order.action == Action.Buy and dealt_units(trade) > 0
        )
        positions = []

        for row in self._client.list_positions(stock_account, unit=Unit.Share):
            if row.quantity <= 0 or row.price <= 0 or row.direction != Action.Buy or row.cond != StockOrderCond.Cash:
                self._logger.warning(
                    f"Ignored Shioaji position {row.code}: {row.direction.value} {row.cond.value} x {row.quantity} at {row.price}. "
                    "The app manages long cash positions with a cost only."
                )
                continue

            positions.append(Position(stock_id=row.code, quantity=row.quantity, average_cost=row.price))

        cash = max(balance.acc_balance + payments_due - bought_today, 0)

        return Account(account_id=stock_account.account_id, cash=cash, positions=positions)

    def _refusal(self, order: Order, account: Account, contract: StockContract | None) -> tuple[RejectReason, str] | None:
        if order.order_type != OrderType.LIMIT or order.limit_price is None:
            return RejectReason.UNSUPPORTED_ORDER_TYPE, "the Shioaji adapter sends LIMIT orders only"

        if order.time_in_force not in BROKER_TIME_IN_FORCE:
            return (
                RejectReason.UNSUPPORTED_TIME_IN_FORCE,
                f"{order.time_in_force.name} would leave a working order at the broker that the app does not track",
            )

        if order.time_in_force == TimeInForce.FOK and len(lot_parts(order.quantity)) > 1:
            return (
                RejectReason.UNSUPPORTED_TIME_IN_FORCE,
                f"FOK cannot cover {order.quantity} shares: whole lots and odd shares are separate broker orders",
            )

        if contract is None:
            return RejectReason.BROKER_REFUSED, f"Shioaji has no stock contract {order.stock_id}"

        return account.refusal_for(order, self._cost_rule)

    def _broker_order(self, order: Order, lot: StockOrderLot, count: int, index: int) -> BrokerOrder:
        return BrokerOrder(
            price=order.limit_price,
            quantity=count,
            action=BROKER_ACTION[order.action],
            price_type=StockPriceType.LMT,
            order_type=BROKER_TIME_IN_FORCE[order.time_in_force],
            order_lot=lot,
            order_cond=StockOrderCond.Cash,
            account=self._client.stock_account,
            custom_field=f"{order.id.hex[:5]}{index}",
        )

    async def _send(self, contract: StockContract, broker_order: BrokerOrder) -> Trade:
        """Places one broker order and returns its trade once done, or still working after a cancel and a final refresh."""
        tag = broker_order.custom_field

        try:
            trade = await asyncio.to_thread(self._client.place_order, contract, broker_order)

        except Exception as error:
            try:
                trade = await asyncio.to_thread(self._find_trade, tag)

            except Exception as lookup_error:
                self._logger.error(f"Shioaji lookup of the order tagged {tag} failed: {type(lookup_error).__name__}: {lookup_error}")
                trade = None

            if trade is None:
                raise RuntimeError(
                    f"Shioaji did not confirm the order tagged {tag} ({type(error).__name__}: {error}). "
                    "It may have reached the exchange: check the broker's order list"
                ) from error

        trade = await self._refresh(trade)

        if not is_done(trade):
            try:
                await asyncio.to_thread(self._client.cancel_order, trade)

            except Exception as error:
                self._logger.error(f"Shioaji cancel of the order tagged {tag} failed: {type(error).__name__}: {error}")

            trade = await self._refresh(trade)

        self._logger.info(f"Shioaji order {tag}: {describe(trade)}")

        return trade

    async def _refresh(self, trade: Trade) -> Trade:
        """
        Re-reads the broker order until it is done or the polls run out, and returns the freshest copy: the one
        list_trades holds under the same tag, else `trade` itself. A failed read counts as one poll.
        """
        for poll in range(self._max_polls):
            if poll:
                await asyncio.sleep(self._poll_interval_seconds)

            try:
                await asyncio.to_thread(self._client.update_status, trade=trade)
                trade = await asyncio.to_thread(self._listed, trade.order.custom_field) or trade

            except Exception as error:
                self._logger.warning(f"Shioaji status refresh failed: {type(error).__name__}: {error}")
                continue

            if is_done(trade):
                break

        return trade

    def _find_trade(self, tag: str) -> Trade | None:
        self._client.update_status(account=self._client.stock_account)

        return self._listed(tag)

    def _listed(self, tag: str) -> Trade | None:
        return next((trade for trade in self._client.list_trades() if trade.order.custom_field == tag), None)

    def _record_fill(self, order: Order, trade: Trade, held: Position | None) -> None:
        if not dealt_units(trade):
            return

        quantity = dealt_shares(trade)
        price = fill_price(trade)
        cost = self._cost_rule.cost_of(order.action, price, quantity)
        realized_pnl = held.profit_on_sale(quantity, cost.net) if order.action == TradeAction.SELL and held else None

        if order.status == OrderStatus.PENDING:
            order.submit()

        order.fill(quantity, price, cost, realized_pnl)

    def _close(self, order: Order, trades: list[Trade]) -> None:
        """Gives the domain order its final status once every broker order it was split into is accounted for."""
        if order.status == OrderStatus.FILLED:
            return

        statuses = [ORDER_STATUS[trade.status.status] for trade in trades]
        summary = "; ".join(describe(trade) for trade in trades)
        deals_missing = [
            trade
            for trade in trades
            if dealt_units(trade) < trade.status.deal_quantity
            or (ORDER_STATUS[trade.status.status] == OrderStatus.FILLED and dealt_shares(trade) < ordered_shares(trade))
        ]

        if not all(is_done(trade) for trade in trades):
            order.fail(f"still working at the broker after a cancel request, check Shioaji: {summary}")

        elif OrderStatus.FAILED in statuses or deals_missing:
            order.fail(f"unexplained broker result: {summary}")

        elif order.filled_quantity == 0 and all(status == OrderStatus.REJECTED for status in statuses):
            order.reject(RejectReason.BROKER_REFUSED, summary)

        else:
            order.cancel(f"{order.time_in_force.name} unfilled: filled {order.filled_quantity} of {order.quantity}; {summary}")
