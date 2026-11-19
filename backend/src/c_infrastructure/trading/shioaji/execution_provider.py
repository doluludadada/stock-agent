import asyncio
import math
from asyncio import Event, sleep
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import override

import c_infrastructure.trading.shioaji.sdk_reporting  # noqa: F401

# isort: split
from shioaji import Shioaji
from shioaji.account import StockAccount
from shioaji.constant import Action, OrderType as BrokerTimeInForce, Status, StockOrderCond, StockOrderLot, StockPriceType, Unit
from shioaji.contracts import Stock as StockContract
from shioaji.order import Order as BrokerOrder, StockOrder, Trade
from shioaji.position import SettlementV1, StockPosition, StockProfitLoss

from a_domain.model.trading.account import Account, BrokerageStatement, BrokerFill, Mark, Position, Settlement
from a_domain.model.trading.order import Order
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IBrokerExecutionProvider, SendRefusal
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.execution import (
    BrokerOutcomeRule,
    ExchangeOrder,
    FillRule,
    LotSplitRule,
    OrderAcceptanceRule,
    SimulationCashRule,
)
from a_domain.rules.trading.order_rule import BrokerLink
from a_domain.types.enums import ExecutionProvider, LotKind, OrderStatus, RejectReason, TimeInForce, TradeAction
from b_application.config.app_config import AppConfig
from b_application.config.trading_config import ShioajiConfig, ShioajiLogin
from c_infrastructure.market.shioaji_quote_provider import ShioajiConnection, sdk_request

BROKER = "Shioaji"

BROKER_LOT: Mapping[LotKind, StockOrderLot] = {LotKind.BOARD_LOT: StockOrderLot.Common, LotKind.ODD_LOT: StockOrderLot.IntradayOdd}
"""A board-lot order's quantity counts lots, an intraday odd-lot order's counts shares."""

BROKER_ACTION: Mapping[TradeAction, Action] = {TradeAction.BUY: Action.Buy, TradeAction.SELL: Action.Sell}
TRADE_ACTION: Mapping[Action, TradeAction] = {action: trade_action for trade_action, action in BROKER_ACTION.items()}

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
TWSE and TPEx take intraday odd-lot orders as ROD only, from 09:00, and deal them only at the odd-lot session's call
auctions. The adapter sends an odd-lot part right after its board-lot part, so one sent before the first match waits
in the book for it, keeps it working through the matches odd_lot_waits says and then cancels what is left, so no part
is left working.
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

type UnitShares = Mapping[StockOrderLot, int]
"""The shares in one unit of an order's quantity, by the order's lot."""

type Waits = Sequence[float]
"""The seconds a working exchange order waits before each read of its status after the one right after its send."""


class ShioajiExecutionProvider(IBrokerExecutionProvider[StockContract, Trade]):
    """
    The Sinopac broker through the Shioaji client, simulation or production as the login's environment says. The client
    is the one ShioajiQuoteProvider logged in once for the process, so quotes and orders share one login.

    The client is synchronous, so every call runs in a worker thread. Quantities are shares in the domain:
    LotSplitRule splits them into the whole lots, sent as a board-lot order with the order's time in force (IOC or
    FOK), and the rest, sent as an intraday odd-lot order with ODD_LOT_TIME_IN_FORCE (ROD), both LIMIT at the order's
    limit price. FOK is refused for a quantity with odd shares, because an ROD odd-lot part cannot fill or fail with
    the whole quantity.

    Before sending, the order must be one the app sends and the account must cover it (OrderAcceptanceRule, with the
    cash of `get_account`). A stock Shioaji has no contract for is refused first.

    The account's cash is `account_cash`'s: the broker's on a production login, SimulationCashRule's figure while the
    client is on the simulation server. No setting puts that figure on a production login. A read of the account, its
    cash or its statement, refreshes the status of the account's orders of today once (`todays_trades`), within
    shioaji.status_timeout_seconds, and reads today's BUYs and deals from that one answer.

    After sending, the adapter reads each broker order at once and then as its lot's waits say until ORDER_STATUS says
    it is done: a board-lot part as board_lot_waits says, an odd-lot part as odd_lot_waits says, through the odd-lot
    session's first match and the ones after it, since it deals at those only. The order's outcome is still known
    before the run sizes its next order. One still working after its reads, or once the run's stop is set, is
    cancelled and read again (cancelled), within shioaji.cancel_timeout_seconds; BrokerOutcomeRule then gives the
    domain order its final status. No part is sent twice, and none after the stop: the run's refusal_now then refuses.
    If place_order itself raises (a timeout), the adapter looks for the order by its tag before giving up. Each broker
    order carries the tag `custom_field = order.id.hex[:5] + part index`, so a human can match a broker order to its
    journal row. After each update_status the adapter reads the order back from list_trades by that tag, so it does
    not depend on update_status changing the Trade object place_order returned.

    Executions come from the broker's deals: one Order.fill per broker order at its volume-weighted price.
    Fee and tax are TradingCostRule's, which may differ from the broker's discounted fee.

    The server's words can repeat the login's person id, its address and the account number, so nothing the adapter
    logs, raises or records quotes them: a failed SDK call says what the quote provider's failure_of says, and an
    exchange order the broker gave a message for says its status code instead of the message.
    """

    def __init__(
        self,
        connection: ShioajiConnection,
        login: ShioajiLogin,
        config: AppConfig,
        market_clock: IMarketClock,
        logger: ILoggingProvider,
    ) -> None:
        self._connection = connection
        self._client: Shioaji = connection.client
        self._login = login
        self._market_clock = market_clock
        self._logger = logger
        self._cost_rule = config.market.cost_rule()
        self._fill_rule = FillRule(cost_rule=self._cost_rule)
        self._lot_split_rule = LotSplitRule(board_lot_shares=config.market.board_lot_shares)
        self._outcome_rule = BrokerOutcomeRule(broker=BROKER)
        self._acceptance_rule = OrderAcceptanceRule(cost_rule=self._cost_rule)
        self._simulation_cash_rule = SimulationCashRule(simulation_initial_cash=config.shioaji.simulation_initial_cash)
        # The app sends Common and IntradayOdd only (BROKER_LOT). The others are orders the account's holder placed elsewhere, read for
        # the day's fills: after-hours fixed-price trading counts board lots, after-hours odd lots count shares. BlockTrade is left
        # out: the SDK does not say whether its deals count lots or shares, so its fills are skipped with a warning, not guessed.
        self._shares_per_unit: UnitShares = {
            StockOrderLot.Common: config.market.board_lot_shares,
            StockOrderLot.Fixing: config.market.board_lot_shares,
            StockOrderLot.Odd: 1,
            StockOrderLot.IntradayOdd: 1,
        }
        self._config = config
        self._status_timeout_milliseconds = round(config.shioaji.status_timeout_seconds * 1000)

    @override
    async def connect(self) -> None:
        """
        Checks the login ShioajiQuoteProvider holds on the shared client: the stock account, and in production the CA
        certificate that signs orders, which it activates. Raises saying what failed.
        """
        account = self._client.stock_account

        if account is None:
            raise RuntimeError("the login returned no stock account")

        login = self._login

        if login.server.simulation:
            return

        ca_path, ca_password, person_id = login.ca_path, login.ca_password, login.person_id

        if ca_path is None or ca_password is None or person_id is None:
            raise RuntimeError("Shioaji production needs the CA certificate's path, its password and the person id")

        if not await sdk_request(self._client.activate_ca, ca_path, ca_password.get_secret_value(), person_id.get_secret_value()):
            raise RuntimeError(f"the CA certificate at {ca_path} was not activated")

        if not account.signed:
            raise RuntimeError("the stock account has not signed Shioaji's API trading agreement")

    @override
    def link(self) -> BrokerLink:
        """
        Up while the connection's login is the one this adapter's client made and Shioaji has not reported it down: a
        later runtime that logs in again does so on a new client, and this one's is then gone. The server is the
        client's own, as the SDK was made.
        """
        connection = self._connection
        return BrokerLink(
            broker=ExecutionProvider.SHIOAJI,
            up=connection.up and connection.client is self._client,
            simulation=self._client.simulation,
        )

    @override
    async def get_account(self) -> Account:
        stock_account = login_stock_account(self._client)
        rows = await long_cash_rows(self._client, self._logger)
        trades = await todays_trades(self._client, self._status_timeout_milliseconds)
        cash = await account_cash(
            lambda: available_cash(stock_account, self._client, trades, self._shares_per_unit, self._cost_rule),
            rows,
            trades,
            self._client,
            self._shares_per_unit,
            self._cost_rule,
            self._simulation_cash_rule,
            self._logger,
        )
        positions = [replace(position, mark=None) for position in positions_of(rows)]

        return Account(account_id=stock_account.account_id, cash=cash, positions=positions)

    @override
    async def statement(self, sales_from: date, today: date) -> BrokerageStatement:
        stock_account = login_stock_account(self._client)
        rows = await long_cash_rows(self._client, self._logger)
        trades = await todays_trades(self._client, self._status_timeout_milliseconds)
        balance = await account_cash(
            lambda: bank_balance(self._client),
            rows,
            trades,
            self._client,
            self._shares_per_unit,
            self._cost_rule,
            self._simulation_cash_rule,
            self._logger,
        )
        settlements = await sdk_request(self._client.settlements, stock_account)

        return BrokerageStatement(
            read_at=datetime.now(UTC),
            simulation=self._client.simulation,
            balance=balance,
            settlements=[
                Settlement(settles_on=settlement.date, amount=settlement.amount)
                for settlement in settlements
                if isinstance(settlement, SettlementV1)
            ],
            positions=positions_of(rows),
            fills=todays_fills(trades, today, self._shares_per_unit, self._logger),
            sales=await settled_sales(sales_from, today, self._client),
            sales_from=sales_from,
        )

    @override
    async def open_positions(self) -> list[Position]:
        return positions_of(await long_cash_rows(self._client, self._logger))

    @override
    async def place_order(self, order: Order, refusal_now: SendRefusal, stop: Event) -> Order:
        try:
            account = await self.get_account()
            contract = await sdk_request(lambda: self._client.Contracts.Stocks[order.stock_id])
            parts: list[ExchangeOrder] = []
            refusal = (
                refusal_for(order, account, self._acceptance_rule, self._lot_split_rule)
                if isinstance(contract, StockContract)
                else (RejectReason.BROKER_REFUSED, f"Shioaji has no stock contract {order.stock_id}")
            )

            if refusal is None and isinstance(contract, StockContract):
                parts, refusal = await self.send(contract, order, account.position_for(order.stock_id), refusal_now, stop)

            if refusal is not None and not parts:
                order.reject(*refusal, now=datetime.now(UTC))
                self._logger.warning(f"Shioaji order not sent: {order.action} {order.stock_id}: {order.reason}")
                return order

            self._outcome_rule.apply(order, parts, datetime.now(UTC), refusal[1] if refusal is not None else None)

        except Exception as error:
            if not order.status.is_open:
                raise

            order.fail(f"{type(error).__name__}: {error}", now=datetime.now(UTC))
            self._logger.error(f"Shioaji order failed: {order.stock_id}: {order.reason}")

        return order

    @override
    async def send(
        self, contract: StockContract, order: Order, held: Position | None, refusal_now: SendRefusal, stop: Event
    ) -> tuple[list[ExchangeOrder], tuple[RejectReason, str] | None]:
        parts: list[ExchangeOrder] = []

        for index, (lot, shares) in enumerate(self._lot_split_rule.apply(order.quantity)):
            if (refusal := await refusal_now()) is not None:
                return parts, refusal

            trade = await self.place(contract, order, lot, shares, index)
            waits = (
                board_lot_waits(self._config.shioaji) if lot == LotKind.BOARD_LOT else odd_lot_waits(self._market_clock, self._config)
            )
            trade = await concluded(trade, waits, stop, self._client, self._shares_per_unit, self._config.shioaji, self._logger)

            part = exchange_order_of(trade, self._shares_per_unit)
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

        return parts, None

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
            return await sdk_request(self._client.place_order, contract, broker_order)

        except Exception as error:
            trade = await find_trade(broker_order.custom_field, self._client, self._status_timeout_milliseconds, self._logger)

            if trade is None:
                raise RuntimeError(
                    f"Shioaji did not confirm the order tagged {broker_order.custom_field} ({error}). "
                    "It may have reached the exchange: check the broker's order list"
                ) from error

            return trade


def board_lot_waits(shioaji: ShioajiConfig) -> Waits:
    """
    A board-lot part, IOC or FOK, is done once the exchange has it: shioaji.max_polls reads in all,
    shioaji.poll_interval_seconds apart. Any part is read so after its cancel too.
    """
    return [shioaji.poll_interval_seconds] * (shioaji.max_polls - 1)


def odd_lot_waits(market_clock: IMarketClock, config: AppConfig) -> Waits:
    """
    An odd-lot part deals only at the odd-lot session's matches, market_hours.odd_lot_match_seconds apart, so it stays
    working from its send until the later of now and the session's first match, plus shioaji.odd_lot_matches match
    intervals and half of one. It is read half an interval after the first match and after each later one, halfway to
    the next, so each read comes after its match's deal report.
    """
    interval = config.market_hours.odd_lot_match_seconds
    first_read = market_clock.until_odd_lot_session().total_seconds() + interval / 2
    return [first_read, *[interval] * config.shioaji.odd_lot_matches]


def login_stock_account(client: Shioaji) -> StockAccount:
    """The SDK's stock account of the login. Raises while the login gave none."""
    stock_account = client.stock_account

    if stock_account is None:
        raise RuntimeError("Shioaji has no stock account: ShioajiQuoteProvider.connect() logs in first")

    return stock_account


async def todays_trades(client: Shioaji, timeout_milliseconds: int) -> list[Trade]:
    """
    The account's exchange orders of today as the broker lists them once it refreshed the status of all of them: one
    request, which takes longer the more orders the account placed today, so it may take `timeout_milliseconds`.
    """
    stock_account = login_stock_account(client)
    await sdk_request(client.update_status, account=stock_account, timeout=timeout_milliseconds)
    return [trade for trade in await sdk_request(client.list_trades) if trade.order.account == stock_account]


def todays_fills(trades: Sequence[Trade], today: date, unit_shares: UnitShares, logger: ILoggingProvider) -> list[BrokerFill]:
    """Every deal of today's exchange orders (`todays_trades`), in shares."""
    fills: list[BrokerFill] = []

    for trade in trades:
        if not isinstance(trade.order, StockOrder):
            continue

        shares_per_unit = unit_shares.get(trade.order.order_lot)

        if shares_per_unit is None:
            logger.warning(f"Ignored the deals of a Shioaji {trade.order.order_lot.value} order: its unit is unknown.")
            continue

        fills += [
            BrokerFill(
                stock_id=trade.contract.code,
                action=TRADE_ACTION[trade.order.action],
                quantity=deal.quantity * shares_per_unit,
                price=deal.price,
                filled_on=today,
            )
            for deal in trade.status.deals or []
            if deal.quantity > 0 and deal.price > 0
        ]

    return fills


async def settled_sales(first: date, last: date, client: Shioaji) -> list[BrokerFill]:
    """The account's sales the broker settled from `first` to `last`, each with the PnL the broker says it realized."""
    rows = await sdk_request(
        client.list_profit_loss, login_stock_account(client), first.isoformat(), last.isoformat(), unit=Unit.Share
    )

    return [
        BrokerFill(
            stock_id=row.code,
            action=TradeAction.SELL,
            quantity=row.quantity,
            price=row.price,
            filled_on=date.fromisoformat(row.date),
            realized_pnl=row.pnl,
        )
        for row in rows
        if isinstance(row, StockProfitLoss) and row.quantity > 0 and row.price > 0
    ]


async def available_cash(
    broker_account: StockAccount, client: Shioaji, trades: Sequence[Trade], unit_shares: UnitShares, cost_rule: TradingCostRule
) -> float:
    """
    The cash the account can still pay for a BUY with on a production login. Never more than the broker will settle.

    The broker checks a BUY against the trading limit, not the cash, so without this a BUY could exceed the cash and
    default at settlement. Cash is the bank balance, minus the settlement payments still due (T to T+2), minus every
    BUY of today's exchange orders (`trades`) dealt with its fee. A purchase the broker already counts in its
    settlements is subtracted twice, and pending receipts from sales are not counted, so cash can be understated,
    never overstated, as long as the broker reports payments as negative settlement amounts.
    """
    balance = await bank_balance(client)
    settlements = await sdk_request(client.settlements, broker_account)
    payments_due = [min(settlement.amount, 0) for settlement in settlements if isinstance(settlement, SettlementV1)]

    if len(payments_due) < len(settlements):
        raise RuntimeError("Shioaji listed a settlement without an amount")

    bought = bought_today(trades, unit_shares, cost_rule)

    return max(balance + math.fsum(payments_due) - math.fsum(bought.values()), 0)


async def bank_balance(client: Shioaji) -> float:
    """The bank balance of the account's settlement account. Raises where the broker answers it with an error message."""
    balance = await sdk_request(client.account_balance)

    if balance.errmsg:
        raise RuntimeError("Shioaji answered the account balance with an error message")

    return balance.acc_balance


def bought_today(trades: Sequence[Trade], unit_shares: UnitShares, cost_rule: TradingCostRule) -> dict[str, float]:
    """What the BUYs of each stock dealt today (`todays_trades`) cost, with TradingCostRule's fee, by stock."""
    dealt_buys = [
        exchange_order_of(trade, unit_shares)
        for trade in trades
        if trade.order.action == Action.Buy and sum(deal.quantity for deal in trade.status.deals or []) > 0
    ]
    now, costs = datetime.now(UTC), dict[str, float]()

    for part in dealt_buys:
        if part.fill_price is not None:
            cost = -cost_rule.apply(TradeAction.BUY, part.stock_id, part.fill_price, part.dealt_shares, now=now).net
            costs[part.stock_id] = costs.get(part.stock_id, 0.0) + cost

    return costs


async def long_cash_rows(client: Shioaji, logger: ILoggingProvider) -> list[StockPosition]:
    """The account's long cash positions as Shioaji lists them, in shares. Any other row is logged and left out."""
    rows = await sdk_request(client.list_positions, login_stock_account(client), unit=Unit.Share)
    stock_rows = [row for row in rows if isinstance(row, StockPosition)]

    if len(stock_rows) < len(rows):
        raise RuntimeError("Shioaji listed a futures position for the stock account")

    long_rows = []

    for row in stock_rows:
        if row.quantity <= 0 or row.price <= 0 or row.direction != Action.Buy or row.cond != StockOrderCond.Cash:
            logger.warning(
                f"Ignored Shioaji position {row.code}: {row.direction.value} {row.cond.value} x {row.quantity} at {row.price}. "
                "The app manages long cash positions with a cost only."
            )
            continue

        long_rows.append(row)

    return long_rows


def positions_of(rows: Sequence[StockPosition]) -> list[Position]:
    """Shioaji's position rows as the domain's, each marked at the broker's last price and PnL when it reports one."""
    now = datetime.now(UTC)

    return [
        Position(
            stock_id=row.code,
            quantity=row.quantity,
            average_cost=row.price,
            mark=Mark(price=row.last_price, at=now, unrealized_pnl=row.pnl) if row.last_price > 0 else None,
        )
        for row in rows
    ]


async def account_cash(
    production_cash: Callable[[], Awaitable[float]],
    rows: Sequence[StockPosition],
    trades: Sequence[Trade],
    client: Shioaji,
    unit_shares: UnitShares,
    cost_rule: TradingCostRule,
    cash_rule: SimulationCashRule,
    logger: ILoggingProvider,
) -> float:
    """
    The account's cash: `production_cash` on a production login. The simulation server answers the balance with 0 and
    lists no settlement, so there it is SimulationCashRule's figure from `rows`, each with the shares it held at
    yesterday's close (`yd_quantity`), the BUYs of today's exchange orders (`trades`) dealt and every sale the broker
    lists. No record says when the account began, so the sales are asked from the Unix epoch, a day every date library
    names. A figure below zero counts as no cash and is logged, because it means the records and the setting do not fit.
    """
    if not client.simulation:
        return await production_cash()

    held_yesterday: dict[str, int] = {}

    for row in rows:
        held_yesterday[row.code] = held_yesterday.get(row.code, 0) + row.yd_quantity

    bought = bought_today(trades, unit_shares, cost_rule)
    sales = await settled_sales(datetime.fromtimestamp(0, UTC).date(), datetime.now(UTC).date(), client)
    cash = cash_rule.apply(positions_of(rows), held_yesterday, bought, sales)

    if cash < 0:
        logger.warning(
            f"Shioaji simulation cash is {cash:,.0f} by the broker's records and shioaji.simulation_initial_cash "
            f"{cash_rule.simulation_initial_cash:,.0f}: counted as no cash. The setting is under what the account spent."
        )

    return max(cash, 0)


async def stopped_within(stop: Event | None, seconds: float) -> bool:
    """Waits `seconds`, or only until `stop` is set, and says whether it is. None: a wait nothing ends early."""
    if stop is None:
        await sleep(seconds)
        return False

    waiting = [asyncio.ensure_future(sleep(seconds)), asyncio.ensure_future(stop.wait())]

    try:
        await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in waiting:
            task.cancel()

    return stop.is_set()


async def reread(trade: Trade, client: Shioaji, logger: ILoggingProvider) -> Trade:
    """
    One read of the exchange order's status. Returns the freshest copy: the one list_trades holds under the same tag,
    else `trade` itself, also when the read fails.
    """
    try:
        await sdk_request(client.update_status, trade=trade)
        listed = await sdk_request(client.list_trades)

    except Exception as error:
        logger.warning(f"Shioaji status refresh failed: {error}")
        return trade

    return next((known for known in listed if known.order.custom_field == trade.order.custom_field), trade)


async def refreshed(
    trade: Trade, client: Shioaji, unit_shares: UnitShares, waits: Waits, stop: Event | None, logger: ILoggingProvider
) -> Trade:
    """
    Reads the exchange order at once, then after each of `waits`, until it is done, and returns the freshest copy.
    `stop` set ends the waits, never a read in flight. A failed read counts as one read.
    """
    for index, seconds in enumerate([0.0, *waits]):
        if index and await stopped_within(stop, seconds):
            break

        trade = await reread(trade, client, logger)

        if not exchange_order_of(trade, unit_shares).status.is_open:
            break

    return trade


async def concluded(
    trade: Trade, waits: Waits, stop: Event, client: Shioaji, unit_shares: UnitShares, shioaji: ShioajiConfig, logger: ILoggingProvider
) -> Trade:
    """
    The exchange order once the adapter is through with it: read as `waits` says and, when still working then or once
    `stop` is set, cancelled and read again.
    """
    logger.info(f"Shioaji order {trade.order.custom_field}: sent, read until done or for {math.fsum(waits):.1f} s")
    trade = await refreshed(trade, client, unit_shares, waits, stop, logger)

    if not exchange_order_of(trade, unit_shares).status.is_open:
        return trade

    if stop.is_set():
        logger.info(f"Shioaji order {trade.order.custom_field}: the run was cancelled, so what still works of it is cancelled")

    return await cancelled(trade, client, unit_shares, shioaji, logger)


async def cancelled(trade: Trade, client: Shioaji, unit_shares: UnitShares, shioaji: ShioajiConfig, logger: ILoggingProvider) -> Trade:
    """
    Asks the broker to cancel a working exchange order, then reads it as a board-lot part is read, whatever the run's
    stop says, within shioaji.cancel_timeout_seconds in all. Past them, the copy read before the cancel stands, still
    working, so the order says to check the broker, and shutdown stays within the server's stop grace (compose.yml).
    """
    tag = trade.order.custom_field

    try:
        async with asyncio.timeout(shioaji.cancel_timeout_seconds):
            try:
                await sdk_request(client.cancel_order, trade)

            except Exception as error:
                logger.error(f"Shioaji cancel of the order tagged {tag} failed: {error}")

            return await refreshed(trade, client, unit_shares, board_lot_waits(shioaji), None, logger)

    except TimeoutError:
        logger.error(f"Shioaji did not settle the cancel of the order tagged {tag} within {shioaji.cancel_timeout_seconds:g} s")
        return trade


async def find_trade(tag: str, client: Shioaji, timeout_milliseconds: int, logger: ILoggingProvider) -> Trade | None:
    """
    The exchange order with this tag, after re-reading the account's orders, which may take `timeout_milliseconds` on
    a day of many orders (todays_trades). None when absent or the read fails.
    """
    stock_account = client.stock_account

    if stock_account is None:
        return None

    try:
        await sdk_request(client.update_status, account=stock_account, timeout=timeout_milliseconds)
        listed = await sdk_request(client.list_trades)

    except Exception as error:
        logger.error(f"Shioaji lookup of the order tagged {tag} failed: {error}")
        return None

    return next((trade for trade in listed if trade.order.custom_field == tag), None)


def exchange_order_of(trade: Trade, unit_shares: UnitShares) -> ExchangeOrder:
    """
    The exchange order in the domain's terms.

    Shares are the order's units times the shares in one unit of its lot. Deals at one price fill at exactly that price.
    """
    broker_order = trade.order

    if not isinstance(broker_order, StockOrder):
        raise RuntimeError(f"Shioaji trade {broker_order.custom_field} is not a stock order")

    shares_per_unit = unit_shares[broker_order.order_lot]
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
        description=f"{text} (status {trade.status.status_code})" if trade.status.msg else text,
    )


def refusal_for(
    order: Order, account: Account, acceptance_rule: OrderAcceptanceRule, lot_split_rule: LotSplitRule
) -> tuple[RejectReason, str] | None:
    """Why this broker will not take `order` from `account`, or None. Checked before anything is sent."""
    refusal = acceptance_rule.apply(order, account)

    if refusal is not None:
        return refusal

    parts = lot_split_rule.apply(order.quantity)

    if order.time_in_force == TimeInForce.FOK and any(lot == LotKind.ODD_LOT for lot, _ in parts):
        return (
            RejectReason.UNSUPPORTED_TIME_IN_FORCE,
            f"FOK cannot cover {order.quantity} shares: the exchange takes intraday odd lots as ROD only",
        )

    return None
