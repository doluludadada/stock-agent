import asyncio
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import override

from shioaji import Shioaji
from shioaji.account import StockAccount
from shioaji.constant import Action, OrderType as BrokerTimeInForce, Status, StockOrderCond, StockOrderLot, StockPriceType, Unit
from shioaji.contracts import Stock as StockContract
from shioaji.order import Order as BrokerOrder, StockOrder, Trade
from shioaji.position import SettlementV1, StockPosition

from a_domain.model.trading.account import Account, Position
from a_domain.model.trading.order import ExchangeOrder, Order
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IBrokerExecutionProvider
from a_domain.rules.trading.execution import BrokerOutcomeRule, FillRule, LotSplitRule, OrderAcceptanceRule
from a_domain.types.enums import LotKind, OrderStatus, RejectReason, TimeInForce, TradeAction
from b_application.config.app_config import AppConfig

BROKER = "Shioaji"

BROKER_LOT: Mapping[LotKind, StockOrderLot] = {LotKind.BOARD_LOT: StockOrderLot.Common, LotKind.ODD_LOT: StockOrderLot.IntradayOdd}
"""A board-lot order's quantity counts lots, an intraday odd-lot order's counts shares."""

BROKER_ACTION: Mapping[TradeAction, Action] = {TradeAction.BUY: Action.Buy, TradeAction.SELL: Action.Sell}

BROKER_TIME_IN_FORCE: Mapping[TimeInForce, BrokerTimeInForce] = {
    TimeInForce.IOC: BrokerTimeInForce.IOC,
    TimeInForce.FOK: BrokerTimeInForce.FOK,
}
"""
The board-lot part's time in force. OrderAcceptanceRule refuses an ROD order before it is sent: its remainder would keep
working after place_order returns, and the app tracks no working orders.
"""

ODD_LOT_TIME_IN_FORCE = BrokerTimeInForce.ROD
"""
TWSE and TPEx take intraday odd-lot orders as ROD only. The adapter cancels an odd-lot part still working after its
polls, as it does a board-lot part, so no part is left working.
"""

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
What each Shioaji status means in the domain order lifecycle (OrderStatus.next_statuses).

- PendingSubmit: on its way, not acknowledged yet.
- PreSubmitted: a reservation the broker holds until the session opens, so it is working.
- PartFilled: part executed, the rest still working (SUBMITTED -> SUBMITTED).
- Cancelled: stopped with the rest unfilled: an IOC remainder, a FOK kill, or the adapter's cancel.
- Failed: the broker or the exchange refused it.
- Inactive: done, with no documented meaning, so it is reported as an error for a human to look at.
"""


class ShioajiExecutionProvider(IBrokerExecutionProvider[StockAccount, StockContract, Trade]):
    """
    The Sinopac broker through the Shioaji client, simulation or production as `shioaji.simulation` says.

    The client is synchronous, so every call runs in a worker thread. Quantities are shares in the domain:
    LotSplitRule splits them into the whole lots, sent as a board-lot order with the order's time in force (IOC or
    FOK), and the rest, sent as an intraday odd-lot order with ODD_LOT_TIME_IN_FORCE (ROD), both LIMIT at the order's
    limit price. FOK is refused for a quantity with odd shares, because an ROD odd-lot part cannot fill or fail with
    the whole quantity.

    Before sending, the order must be one the app sends and the account must cover it (OrderAcceptanceRule, with the
    cash that `cash` reads). A stock Shioaji has no contract for is refused first.

    After sending, the adapter refreshes each broker order until ORDER_STATUS says it is done. One still
    working after the polls is cancelled and refreshed again; BrokerOutcomeRule then gives the domain order
    its final status. If place_order itself raises (a timeout), the adapter looks for the order by its tag
    before giving up. Each broker order carries the tag `custom_field = order.id.hex[:5] + part index`, so a
    human can match a broker order to its journal row. After each update_status the adapter reads the order
    back from list_trades by that tag, so it does not depend on update_status changing the Trade object
    place_order returned.

    Executions come from the broker's deals: one Order.fill per broker order at its volume-weighted price.
    Fee and tax are TradingCostRule's, which may differ from the broker's discounted fee.
    """

    def __init__(self, client: Shioaji, config: AppConfig, logger: ILoggingProvider) -> None:
        self._client = client
        self._credentials = config.shioaji
        self._logger = logger
        self._cost_rule = config.market.cost_rule()
        self._fill_rule = FillRule(cost_rule=self._cost_rule)
        self._lot_split_rule = LotSplitRule(board_lot_shares=config.market.board_lot_shares)
        self._outcome_rule = BrokerOutcomeRule(broker=BROKER)
        self._acceptance_rule = OrderAcceptanceRule(cost_rule=self._cost_rule)
        self._shares_per_unit = {StockOrderLot.Common: config.market.board_lot_shares, StockOrderLot.IntradayOdd: 1}
        self._poll_interval_seconds = config.shioaji.poll_interval_seconds
        self._max_polls = config.shioaji.max_polls

    @override
    async def connect(self) -> None:
        """Logs in, then in production activates the CA certificate that signs orders. Raises saying what failed."""
        credentials = self._credentials

        if credentials.api_key is None or credentials.secret_key is None:
            raise RuntimeError(f"Shioaji needs {', '.join(credentials.missing_credentials())}")

        api_key, secret_key = credentials.api_key.get_secret_value(), credentials.secret_key.get_secret_value()
        await asyncio.to_thread(self._client.login, api_key=api_key, secret_key=secret_key, subscribe_trade=False)
        account = self._client.stock_account

        if account is None:
            raise RuntimeError("the login returned no stock account")

        if credentials.simulation:
            return

        ca_path, ca_password, person_id = credentials.ca_path, credentials.ca_password, credentials.person_id

        if ca_path is None or ca_password is None or person_id is None:
            raise RuntimeError(f"Shioaji production needs {', '.join(credentials.missing_credentials())}")

        if not await asyncio.to_thread(
            self._client.activate_ca, ca_path, ca_password.get_secret_value(), person_id.get_secret_value()
        ):
            raise RuntimeError(f"the CA certificate at {ca_path} was not activated")

        if not account.signed:
            raise RuntimeError(f"stock account {account.account_id} has not signed Shioaji's API trading agreement")

    @override
    async def get_account(self) -> Account:
        stock_account = self._client.stock_account

        if stock_account is None:
            raise RuntimeError("Shioaji has no stock account: connect() logs in first")

        cash = await self.cash(stock_account)
        rows = await asyncio.to_thread(self._client.list_positions, stock_account, unit=Unit.Share)
        stock_rows = [row for row in rows if isinstance(row, StockPosition)]

        if len(stock_rows) < len(rows):
            raise RuntimeError("Shioaji listed a futures position for the stock account")

        positions = []

        for row in stock_rows:
            if row.quantity <= 0 or row.price <= 0 or row.direction != Action.Buy or row.cond != StockOrderCond.Cash:
                self._logger.warning(
                    f"Ignored Shioaji position {row.code}: {row.direction.value} {row.cond.value} x {row.quantity} at {row.price}. "
                    "The app manages long cash positions with a cost only."
                )
                continue

            positions.append(Position(stock_id=row.code, quantity=row.quantity, average_cost=row.price))

        return Account(account_id=stock_account.account_id, cash=cash, positions=positions)

    @override
    async def place_order(self, order: Order) -> Order:
        try:
            account = await self.get_account()
            contract = await asyncio.to_thread(lambda: self._client.Contracts.Stocks[order.stock_id])
            refusal = (
                self.refusal_for(order, account)
                if isinstance(contract, StockContract)
                else (RejectReason.BROKER_REFUSED, f"Shioaji has no stock contract {order.stock_id}")
            )

            if refusal is not None:
                order.reject(*refusal, now=datetime.now(UTC))
                self._logger.warning(f"Shioaji order not sent: {order.action} {order.stock_id}: {order.reason}")
                return order

            parts = await self.send(contract, order, account.position_for(order.stock_id))
            self._outcome_rule.apply(order, parts, datetime.now(UTC))

        except Exception as error:
            if not order.status.is_open:
                raise

            order.fail(f"{type(error).__name__}: {error}", now=datetime.now(UTC))
            self._logger.error(f"Shioaji order failed: {order.stock_id}: {order.reason}")

        return order

    @override
    def refusal_for(self, order: Order, account: Account) -> tuple[RejectReason, str] | None:
        refusal = self._acceptance_rule.apply(order, account)

        if refusal is not None:
            return refusal

        parts = self._lot_split_rule.apply(order.quantity)

        if order.time_in_force == TimeInForce.FOK and any(lot == LotKind.ODD_LOT for lot, _ in parts):
            return (
                RejectReason.UNSUPPORTED_TIME_IN_FORCE,
                f"FOK cannot cover {order.quantity} shares: the exchange takes intraday odd lots as ROD only",
            )

        return None

    @override
    async def cash(self, broker_account: StockAccount) -> float:
        """
        The broker checks a BUY against the trading limit, not the cash, so without this a BUY could exceed the cash and
        default at settlement. Cash is the bank balance, minus the settlement payments still due (T to T+2), minus every
        BUY the broker lists as dealt today with its fee. A purchase the broker already counts in its settlements is
        subtracted twice, and pending receipts from sales are not counted, so cash can be understated, never overstated,
        as long as the broker reports payments as negative settlement amounts.
        """
        balance = await asyncio.to_thread(self._client.account_balance)

        if balance.errmsg:
            raise RuntimeError(f"Shioaji account balance unavailable: {balance.errmsg}")

        settlements = await asyncio.to_thread(self._client.settlements, broker_account)
        payments_due = [min(settlement.amount, 0) for settlement in settlements if isinstance(settlement, SettlementV1)]

        if len(payments_due) < len(settlements):
            raise RuntimeError("Shioaji listed a settlement without an amount")

        await asyncio.to_thread(self._client.update_status, account=broker_account)
        trades = await asyncio.to_thread(self._client.list_trades)
        dealt_buys = [
            self.exchange_order_of(trade)
            for trade in trades
            if trade.order.account == broker_account
            and trade.order.action == Action.Buy
            and sum(deal.quantity for deal in trade.status.deals or []) > 0
        ]
        now = datetime.now(UTC)
        bought_today = math.fsum(
            -self._cost_rule.apply(TradeAction.BUY, part.stock_id, part.fill_price, part.dealt_shares, now=now).net
            for part in dealt_buys
            if part.fill_price is not None
        )

        return max(balance.acc_balance + math.fsum(payments_due) - bought_today, 0)

    @override
    async def send(self, contract: StockContract, order: Order, held: Position | None) -> list[ExchangeOrder]:
        parts: list[ExchangeOrder] = []

        for index, (lot, shares) in enumerate(self._lot_split_rule.apply(order.quantity)):
            trade = await self.refresh(await self.place(contract, order, lot, shares, index))

            if self.exchange_order_of(trade).status.is_open:
                trade = await self.cancel(trade)

            part = self.exchange_order_of(trade)
            parts.append(part)
            self._logger.info(f"Shioaji order {trade.order.custom_field}: {part.description}")

            if part.fill_price is not None:
                now = datetime.now(UTC)
                cost, realized_pnl = self._fill_rule.apply(order, part.dealt_shares, part.fill_price, held, now=now)
                # The first fill submits the order; a later part's fill finds it SUBMITTED, which may stay SUBMITTED.
                order.submit(now=now)
                order.fill(part.dealt_shares, part.fill_price, cost.fee, cost.tax, realized_pnl, now=now)

            if part.status.is_open:
                break

        return parts

    @override
    async def place(self, contract: StockContract, order: Order, lot: LotKind, shares: int, index: int) -> Trade:
        """
        One LIMIT exchange order for `shares` of `order` at its limit price, tagged `order.id.hex[:5] + index`: a board-lot
        part with the order's time in force, an odd-lot part ROD. If place_order raises (a timeout), the order is looked up
        by its tag before giving up.
        """
        if order.limit_price is None:
            raise ValueError(f"order {order.id} has no limit price to send")

        broker_order = BrokerOrder(
            price=order.limit_price,
            quantity=shares // self._shares_per_unit[BROKER_LOT[lot]],
            action=BROKER_ACTION[order.action],
            price_type=StockPriceType.LMT,
            order_type=BROKER_TIME_IN_FORCE[order.time_in_force] if lot == LotKind.BOARD_LOT else ODD_LOT_TIME_IN_FORCE,
            order_lot=BROKER_LOT[lot],
            order_cond=StockOrderCond.Cash,
            account=self._client.stock_account,
            custom_field=f"{order.id.hex[:5]}{index}",
        )

        try:
            return await asyncio.to_thread(self._client.place_order, contract, broker_order)

        except Exception as error:
            trade = await self.find_trade(broker_order.custom_field)

            if trade is None:
                raise RuntimeError(
                    f"Shioaji did not confirm the order tagged {broker_order.custom_field} ({type(error).__name__}: {error}). "
                    "It may have reached the exchange: check the broker's order list"
                ) from error

            return trade

    @override
    async def refresh(self, trade: Trade) -> Trade:
        """
        Returns the freshest copy: the one list_trades holds under the same tag, else `trade` itself. A failed read counts
        as one poll.
        """
        tag = trade.order.custom_field

        for poll in range(self._max_polls):
            if poll:
                await asyncio.sleep(self._poll_interval_seconds)

            try:
                await asyncio.to_thread(self._client.update_status, trade=trade)
                listed = await asyncio.to_thread(self._client.list_trades)

            except Exception as error:
                self._logger.warning(f"Shioaji status refresh failed: {type(error).__name__}: {error}")
                continue

            trade = next((known for known in listed if known.order.custom_field == tag), trade)

            if not self.exchange_order_of(trade).status.is_open:
                break

        return trade

    @override
    async def cancel(self, trade: Trade) -> Trade:
        try:
            await asyncio.to_thread(self._client.cancel_order, trade)

        except Exception as error:
            self._logger.error(
                f"Shioaji cancel of the order tagged {trade.order.custom_field} failed: {type(error).__name__}: {error}"
            )

        return await self.refresh(trade)

    @override
    async def find_trade(self, tag: str) -> Trade | None:
        stock_account = self._client.stock_account

        if stock_account is None:
            return None

        try:
            await asyncio.to_thread(self._client.update_status, account=stock_account)
            listed = await asyncio.to_thread(self._client.list_trades)

        except Exception as error:
            self._logger.error(f"Shioaji lookup of the order tagged {tag} failed: {type(error).__name__}: {error}")
            return None

        return next((trade for trade in listed if trade.order.custom_field == tag), None)

    @override
    def exchange_order_of(self, trade: Trade) -> ExchangeOrder:
        """Shares are the order's units times the shares in one unit of its lot. Deals at one price fill at exactly that price."""
        broker_order = trade.order

        if not isinstance(broker_order, StockOrder):
            raise RuntimeError(f"Shioaji trade {broker_order.custom_field} is not a stock order")

        shares_per_unit = self._shares_per_unit[broker_order.order_lot]
        deals = trade.status.deals or []
        dealt_units = sum(deal.quantity for deal in deals)
        prices = {deal.price for deal in deals}
        fill_price = None

        if dealt_units:
            fill_price = prices.pop() if len(prices) == 1 else math.fsum(deal.price * deal.quantity for deal in deals) / dealt_units

        unit = "lots" if broker_order.order_lot == StockOrderLot.Common else "shares"
        text = (
            f"{broker_order.order_lot.value} {broker_order.quantity} {unit} {broker_order.order_type.value} "
            f"{trade.status.status.value}, dealt {dealt_units * shares_per_unit} shares"
        )

        return ExchangeOrder(
            stock_id=trade.contract.code,
            status=ORDER_STATUS[trade.status.status],
            ordered_shares=broker_order.quantity * shares_per_unit,
            dealt_shares=dealt_units * shares_per_unit,
            reported_dealt_shares=trade.status.deal_quantity * shares_per_unit,
            fill_price=fill_price,
            description=f"{text} ({trade.status.msg})" if trade.status.msg else text,
        )
