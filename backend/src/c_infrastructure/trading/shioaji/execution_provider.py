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
from shioaji.order import BaseOrder, Order as BrokerOrder, StockOrder, Trade
from shioaji.position import SettlementV1, StockPosition, StockProfitLoss

from a_domain.model.trading.account import Account, BrokerageStatement, BrokerFill, Mark, Position, Settlement
from a_domain.model.trading.order import Order, volume_weighted_price
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
from a_domain.rules.trading.tick import limit_within_band
from a_domain.types.enums import ExecutionProvider, LotKind, OrderStatus, RejectReason, TimeInForce, TradeAction
from a_domain.types.errors import BrokerNotAnswering
from b_application.config.app_config import AppConfig
from b_application.config.trading_config import ShioajiConfig, ShioajiLogin
from c_infrastructure.market.shioaji_quote_provider import ShioajiConnection, ShioajiSession, sdk_request

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

    Before sending, the order's own limit moves inside the day's price band its contract names (within_band), and then
    the order must be one the app sends and the account must cover it (OrderAcceptanceRule, with the cash of
    `get_account`). A stock Shioaji has no contract for is refused first.

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
    Each broker order carries the tag `custom_field = order.id.hex[:5] + part index` (Order.tag), so a human can match a
    broker order to its journal row. The tag may repeat across the account's orders, every user's, so the adapter knows
    a listed order as one of its parts only by its tag, stock, action, lot, quantity and price together
    (is_exchange_order). After each update_status it reads the order back from list_trades so, never depending on
    update_status changing the Trade object place_order returned.

    If place_order itself raises (the SDK's wait for the answer timed out), the order may have reached SinoPac anyway:
    the SDK publishes the request before it waits and drops an answer that comes later. The adapter then looks for it
    at once and again after each of board_lot_waits (listed_trade), since SinoPac lists such an order a moment later
    (about a second on 2026-11-19), within shioaji.status_timeout_seconds in all and until the run's stop. One it finds
    goes on as if confirmed. One it does not find, and a part still working after its cancel, leave the order
    UNCONFIRMED, with nothing sent after it; `settle` settles it later from SinoPac's record of the day
    (OrderSettlement), which only reads and cancels.

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
        self._session = ShioajiSession(connection, connection.client)
        self._login = login
        self._market_clock = market_clock
        self._logger = logger
        self._cost_rule = config.market.cost_rule()
        self._fill_rule, self._acceptance_rule = FillRule(cost_rule=self._cost_rule), OrderAcceptanceRule(cost_rule=self._cost_rule)
        self._lot_split_rule = LotSplitRule(board_lot_shares=config.market.board_lot_shares)
        self._outcome_rule = BrokerOutcomeRule(broker=BROKER)
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
        self._sessions_without_band: set[date] = set()

    @override
    async def connect(self) -> None:
        """
        Checks the login ShioajiQuoteProvider holds on the shared client: the stock account, and in production the CA
        certificate that signs orders, which it activates. Raises saying what failed.
        """
        account = self._session.client.stock_account

        if account is None:
            raise RuntimeError("the login returned no stock account")

        login = self._login

        if login.server.simulation:
            return

        ca_path, ca_password, person_id = login.ca_path, login.ca_password, login.person_id

        if ca_path is None or ca_password is None or person_id is None:
            raise RuntimeError("Shioaji production needs the CA certificate's path, its password and the person id")

        if not await sdk_request(
            self._session, self._session.client.activate_ca, ca_path, ca_password.get_secret_value(), person_id.get_secret_value()
        ):
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
            up=connection.up and connection.client is self._session.client,
            simulation=self._session.client.simulation,
        )

    @override
    async def get_account(self) -> Account:
        stock_account = login_stock_account(self._session.client)
        rows = await long_cash_rows(self._session, self._logger)
        trades = await todays_trades(self._session, self._status_timeout_milliseconds)
        cash = await account_cash(
            lambda: available_cash(stock_account, self._session, trades, self._shares_per_unit, self._cost_rule),
            rows,
            trades,
            self._session,
            self._shares_per_unit,
            self._cost_rule,
            self._simulation_cash_rule,
            self._logger,
        )
        positions = [replace(position, mark=None) for position in positions_of(rows)]

        return Account(account_id=stock_account.account_id, cash=cash, positions=positions)

    @override
    async def statement(self, sales_from: date, today: date) -> BrokerageStatement:
        stock_account = login_stock_account(self._session.client)
        rows = await long_cash_rows(self._session, self._logger)
        trades = await todays_trades(self._session, self._status_timeout_milliseconds)
        balance = await account_cash(
            lambda: bank_balance(self._session),
            rows,
            trades,
            self._session,
            self._shares_per_unit,
            self._cost_rule,
            self._simulation_cash_rule,
            self._logger,
        )
        settlements = await sdk_request(self._session, self._session.client.settlements, stock_account)

        return BrokerageStatement(
            read_at=datetime.now(UTC),
            simulation=self._session.client.simulation,
            balance=balance,
            settlements=[
                Settlement(settles_on=settlement.date, amount=settlement.amount)
                for settlement in settlements
                if isinstance(settlement, SettlementV1)
            ],
            positions=positions_of(rows),
            fills=todays_fills(trades, today, self._shares_per_unit, self._logger),
            sales=await settled_sales(sales_from, today, self._session),
            sales_from=sales_from,
        )

    @override
    async def open_positions(self) -> list[Position]:
        return positions_of(await long_cash_rows(self._session, self._logger))

    @override
    async def trading_available(self) -> float | None:
        """
        SinoPac's trading limit of the stock account (trading_limits, its limit on electronic trading): its
        trading_available while positive. A read that fails is no limit known, logged by what failed: SinoPac holds
        every order to its own limit whatever the site planned, so the read only lets a follow plan inside it.
        """
        try:
            limits = await sdk_request(self._session, self._session.client.trading_limits, login_stock_account(self._session.client))
        except BrokerNotAnswering as error:
            self._logger.warning(f"Shioaji trading limit not read: {error}")
            return None

        return float(limits.trading_available) if limits is not None and limits.trading_available > 0 else None

    @override
    async def place_order(self, order: Order, refusal_now: SendRefusal, stop: Event) -> Order:
        try:
            account = await self.get_account()
            contract = await sdk_request(self._session, lambda: self._session.client.Contracts.Stocks[order.stock_id])
            parts: list[ExchangeOrder] = []
            within_band(order, contract, self._market_clock, self._config, self._sessions_without_band, self._logger)
            refusal = refusal_for(order, contract, account, self._acceptance_rule, self._lot_split_rule)

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

            order.fail_if_open(f"{type(error).__name__}: {error}", now=datetime.now(UTC))
            self._logger.error(f"Shioaji order {order.status.value}: {order.stock_id}: {type(error).__name__}: {error}")

        return order

    @override
    async def send(
        self, contract: StockContract, order: Order, held: Position | None, refusal_now: SendRefusal, stop: Event
    ) -> tuple[list[ExchangeOrder], tuple[RejectReason, str] | None]:
        parts: list[ExchangeOrder] = []

        for index, (lot, shares) in enumerate(self._lot_split_rule.apply(order.quantity)):
            if (refusal := await refusal_now()) is not None:
                return parts, refusal

            if (trade := await self.place(contract, order, lot, shares, index, stop)) is None:
                parts.append(unlisted_part(order, lot, shares, index))
                break

            waits = (
                board_lot_waits(self._config.shioaji) if lot == LotKind.BOARD_LOT else odd_lot_waits(self._market_clock, self._config)
            )
            trade = await concluded(trade, waits, stop, self._session, self._shares_per_unit, self._config.shioaji, self._logger)

            part = exchange_order_of(trade, self._shares_per_unit)
            parts.append(part)
            self._logger.info(f"Shioaji order {trade.order.custom_field}: {part.description}")

            if part.fill_price is not None:
                record_fill(order, part.dealt_shares, part.fill_price, held, self._fill_rule, datetime.now(UTC))

            if part.status.is_open:
                break

        return parts, None

    @override
    async def place(self, contract: StockContract, order: Order, lot: LotKind, shares: int, index: int, stop: Event) -> Trade | None:
        """
        One LIMIT exchange order for `shares` of `order` (exchange_order_for). If place_order raises (a timeout), the
        order is looked for at once and after each of board_lot_waits (listed_trade), within
        shioaji.status_timeout_seconds in all and until `stop` is set; None while SinoPac does not list it.
        """
        sent = exchange_order_for(order, lot, shares, index, self._session.client.stock_account, self._shares_per_unit)

        try:
            return await sdk_request(self._session, self._session.client.place_order, contract, sent)

        except Exception as error:
            self._logger.warning(
                f"Shioaji did not confirm the order tagged {sent.custom_field} ({error}): it is looked for in the account's orders"
            )
            waits, timeout = board_lot_waits(self._config.shioaji), self._config.shioaji.status_timeout_seconds
            return await listed_trade(order.stock_id, sent, waits, stop, self._session, timeout, self._logger)

    @override
    async def settle(self, order: Order) -> None:
        """
        From SinoPac's record of today, the day the order was sent (settled_parts), since list_trades holds today's
        orders alone and OrderSettlement fails an order of an earlier session itself: each of its parts SinoPac lists,
        cancelled first while it still works, and each it does not list. A part the send never reached reads as one
        SinoPac does not list yet, so such an order waits until its session's deals are final (market_hours.settled, as
        IMarketClock.last_settled_session counts it). What the listed parts dealt beyond what the order holds is recorded
        on it part by part, as a run records a part (unrecorded_fills), and BrokerOutcomeRule decides. A SELL's realized
        PnL takes its cost from the position SinoPac lists after the sale, which a sale of every share leaves none of:
        the order then keeps no realized PnL, an earlier part's included, and says it was not computed.

        The parts are known by the limit they were sent at: the order's own limit moves inside its session's price band
        first, as place_order moved it before the send (within_band), so a part sent at the band's edge is found also
        for an order a stopped process left PENDING with the limit it was decided at.
        """
        session, lots = self._market_clock.to_trading_date(order.created_at), self._lot_split_rule.apply(order.quantity)
        contract = await sdk_request(self._session, lambda: self._session.client.Contracts.Stocks[order.stock_id])
        within_band(order, contract, self._market_clock, self._config, self._sessions_without_band, self._logger)
        trades = await todays_trades(self._session, self._status_timeout_milliseconds)
        read, parts = await settled_parts(
            order, lots, trades, self._session, self._shares_per_unit, self._config.shioaji, self._logger
        )
        fills, now, sale = (
            unrecorded_fills(read, order.filled_quantity, self._shares_per_unit),
            self._market_clock.now(),
            order.action == TradeAction.SELL,
        )
        held = position_of(positions_of(await long_cash_rows(self._session, self._logger)), order.stock_id) if sale and fills else None

        for shares, price in fills:
            record_fill(order, shares, price, held, self._fill_rule, now)

        self._outcome_rule.apply(order, parts, now, final=self._market_clock.last_settled_session() >= session)

        if sale and fills and held is None:
            order.drop_realized_pnl(
                f"realized PnL not computed: {BROKER} lists no {order.stock_id} position after the sale to take its cost from"
            )


def day_band(contract: StockContract, session: date) -> tuple[float, float] | None:
    """
    The contract's price band, (limit_down, limit_up), while it is the band of `session`: both edges positive and its
    update_date (YYYY/MM/DD) that day. None for any other: the process reads the contracts once, at its login, so one
    that runs past that day holds an older day's band.
    """
    try:
        updated_on = date.strptime(contract.update_date, "%Y/%m/%d")
    except ValueError:
        return None

    if updated_on != session or contract.limit_down <= 0 or contract.limit_up <= 0:
        return None

    return contract.limit_down, contract.limit_up


def within_band(
    order: Order, contract: object, market_clock: IMarketClock, config: AppConfig, warned: set[date], logger: ILoggingProvider
) -> None:
    """
    Moves `order`'s own limit inside the price band of its session that its stock's `contract` names (day_band,
    limit_within_band), which TWSE and TPEx refuse an order priced past, so its journal row, its parts and their
    settlement all hold the price sent. Without that day's band the limit stays as LimitPriceRule set it, and the first
    order of each session says so (`warned`). A stock with no contract is refusal_for's.
    """
    if not isinstance(contract, StockContract) or order.limit_price is None:
        return

    session = market_clock.to_trading_date(order.created_at)

    if (band := day_band(contract, session)) is not None:
        rule = config.limit_price_rule()
        order.limit_price = limit_within_band(rule, order.action, order.stock_id, order.price_at_signal, order.limit_price, *band)
        return

    if session not in warned:
        warned.add(session)
        logger.warning(
            f"Shioaji's contracts hold no price band of {session}, so each limit is sent as set, and the exchange refuses "
            "one past that day's band: they were read at the login"
        )


def exchange_order_for(
    order: Order, lot: LotKind, shares: int, index: int, account: StockAccount | None, unit_shares: UnitShares
) -> BrokerOrder:
    """
    The LIMIT exchange order of `order`'s part `index`: `shares` of it at its limit price, tagged Order.tag(index), a
    board-lot part with the order's time in force, an odd-lot part ROD. `place` sends it, and the broker's record
    holds it as the part (is_exchange_order).
    """
    if order.limit_price is None:
        raise ValueError(f"order {order.id} has no limit price to send")

    return BrokerOrder(
        price=order.limit_price,
        quantity=shares // unit_shares[BROKER_LOT[lot]],
        action=BROKER_ACTION[order.action],
        price_type=StockPriceType.LMT,
        order_type=BROKER_TIME_IN_FORCE[order.time_in_force] if lot == LotKind.BOARD_LOT else ODD_LOT_TIME_IN_FORCE,
        order_lot=BROKER_LOT[lot],
        order_cond=StockOrderCond.Cash,
        account=account,
        custom_field=order.tag(index),
    )


def is_exchange_order(trade: Trade, stock_id: str, sent: BaseOrder, logger: ILoggingProvider) -> bool:
    """
    Whether the broker's `trade` is the exchange order `sent` for `stock_id`: the same tag, and the same stock, action,
    lot, quantity and price, since a tag's five hex digits and part index may repeat across the account's orders of
    every user, and settling another order's part would cancel it. One of the same tag and stock that differs in
    another field is logged at WARNING with the fields: nobody verified yet that SinoPac keeps an order's quantity and
    price as sent after a partial deal or a cancel, and a part it changed would read as one it does not list.
    """
    listed = trade.order

    if not isinstance(listed, StockOrder) or not isinstance(sent, StockOrder):
        return False

    if listed.custom_field != sent.custom_field or trade.contract.code != stock_id:
        return False

    fields = [
        ("action", listed.action == sent.action, listed.action.value, sent.action.value),
        ("lot", listed.order_lot == sent.order_lot, listed.order_lot.value, sent.order_lot.value),
        ("quantity", listed.quantity == sent.quantity, listed.quantity, sent.quantity),
        ("price", math.isclose(listed.price, sent.price), listed.price, sent.price),
    ]

    if differing := [f"{name} is {held} where {given} was sent" for name, same, held, given in fields if not same]:
        logger.warning(
            f"{BROKER} lists an order tagged {sent.custom_field} of {stock_id} whose {', '.join(differing)}: it is not taken "
            "as that part"
        )

    return not differing


async def settled_parts(
    order: Order,
    lots: Sequence[tuple[LotKind, int]],
    trades: Sequence[Trade],
    session: ShioajiSession,
    unit_shares: UnitShares,
    shioaji: ShioajiConfig,
    logger: ILoggingProvider,
) -> tuple[list[Trade], list[ExchangeOrder]]:
    """
    Each part of `order` (`lots`, as LotSplitRule splits it) as `trades`, the broker's record of today, holds it:
    cancelled first while it still works, then read; unlisted_part while the record holds none that is_exchange_order
    of it. The trades read, in part order, and every part's ExchangeOrder.
    """
    read: list[Trade] = []
    parts: list[ExchangeOrder] = []

    for index, (lot, shares) in enumerate(lots):
        sent = exchange_order_for(order, lot, shares, index, session.client.stock_account, unit_shares)

        if (trade := next((listed for listed in trades if is_exchange_order(listed, order.stock_id, sent, logger)), None)) is None:
            parts.append(unlisted_part(order, lot, shares, index))
            continue

        if exchange_order_of(trade, unit_shares).status.is_open:
            trade = await cancelled(trade, session, unit_shares, shioaji, logger)

        read.append(trade)
        parts.append(exchange_order_of(trade, unit_shares))

    return read, parts


def unlisted_part(order: Order, lot: LotKind, shares: int, index: int) -> ExchangeOrder:
    """A part of `order` the broker does not list by its tag, as UNCONFIRMED: sent or not, its outcome is not known."""
    return ExchangeOrder(
        stock_id=order.stock_id,
        status=OrderStatus.UNCONFIRMED,
        ordered_shares=shares,
        dealt_shares=0,
        reported_dealt_shares=0,
        fill_price=None,
        description=f"{BROKER_LOT[lot].value} {shares} shares tagged {order.tag(index)}, which {BROKER} does not list",
    )


def record_fill(order: Order, shares: int, price: float, held: Position | None, fill_rule: FillRule, now: datetime) -> None:
    """
    Records what one part dealt on the order, with FillRule's fee, tax and realized PnL. The first fill submits the
    order; a later part's fill finds it SUBMITTED, which may stay SUBMITTED.
    """
    cost, realized_pnl = fill_rule.apply(order, shares, price, held, now=now)
    order.submit(now=now)
    order.fill(shares, price, cost.fee, cost.tax, realized_pnl, now=now)


def unrecorded_fills(trades: Sequence[Trade], recorded: int, unit_shares: UnitShares) -> list[tuple[int, float]]:
    """
    What each of an order's parts (`trades`, in part order) dealt beyond the first `recorded` shares, which the order
    holds already: (shares, price) at their volume_weighted_price, one per part that dealt more, as a run records a
    part. A part's deals are recorded whole and in the broker's order, so the recorded ones are always the first.
    """
    skip, fills = recorded, list[tuple[int, float]]()

    for trade in trades:
        if not isinstance(trade.order, StockOrder):
            continue

        deals = list[tuple[float, int]]()

        for deal in trade.status.deals or []:
            dealt = deal.quantity * unit_shares[trade.order.order_lot]
            taken = min(skip, dealt)
            skip -= taken
            deals.append((deal.price, dealt - taken))

        if (price := volume_weighted_price(deals)) is not None:
            fills.append((sum(shares for _, shares in deals), price))

    return fills


def position_of(positions: Sequence[Position], stock_id: str) -> Position | None:
    """The position of `stock_id` among `positions`, or None while none holds it."""
    return next((position for position in positions if position.stock_id == stock_id), None)


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


async def todays_trades(session: ShioajiSession, timeout_milliseconds: int) -> list[Trade]:
    """
    The account's exchange orders of today as the broker lists them once it refreshed the status of all of them: one
    request, which takes longer the more orders the account placed today, so it may take `timeout_milliseconds`.
    """
    stock_account = login_stock_account(session.client)
    await sdk_request(session, session.client.update_status, account=stock_account, timeout=timeout_milliseconds)
    return [trade for trade in await sdk_request(session, session.client.list_trades) if trade.order.account == stock_account]


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


async def settled_sales(first: date, last: date, session: ShioajiSession) -> list[BrokerFill]:
    """The account's sales the broker settled from `first` to `last`, each with the PnL the broker says it realized."""
    rows = await sdk_request(
        session,
        session.client.list_profit_loss,
        login_stock_account(session.client),
        first.isoformat(),
        last.isoformat(),
        unit=Unit.Share,
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
    broker_account: StockAccount, session: ShioajiSession, trades: Sequence[Trade], unit_shares: UnitShares, cost_rule: TradingCostRule
) -> float:
    """
    The cash the account can still pay for a BUY with on a production login. Never more than the broker will settle.

    The broker checks a BUY against the trading limit, not the cash, so without this a BUY could exceed the cash and
    default at settlement. Cash is the bank balance, minus the settlement payments still due (T to T+2), minus every
    BUY of today's exchange orders (`trades`) dealt with its fee. A purchase the broker already counts in its
    settlements is subtracted twice, and pending receipts from sales are not counted, so cash can be understated,
    never overstated, as long as the broker reports payments as negative settlement amounts.
    """
    balance = await bank_balance(session)
    settlements = await sdk_request(session, session.client.settlements, broker_account)
    payments_due = [min(settlement.amount, 0) for settlement in settlements if isinstance(settlement, SettlementV1)]

    if len(payments_due) < len(settlements):
        raise RuntimeError("Shioaji listed a settlement without an amount")

    bought = bought_today(trades, unit_shares, cost_rule)

    return max(balance + math.fsum(payments_due) - math.fsum(bought.values()), 0)


async def bank_balance(session: ShioajiSession) -> float:
    """The bank balance of the account's settlement account. Raises where the broker answers it with an error message."""
    balance = await sdk_request(session, session.client.account_balance)

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


async def long_cash_rows(session: ShioajiSession, logger: ILoggingProvider) -> list[StockPosition]:
    """The account's long cash positions as Shioaji lists them, in shares. Any other row is logged and left out."""
    rows = await sdk_request(session, session.client.list_positions, login_stock_account(session.client), unit=Unit.Share)
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
    session: ShioajiSession,
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
    if not session.client.simulation:
        return await production_cash()

    held_yesterday: dict[str, int] = {}

    for row in rows:
        held_yesterday[row.code] = held_yesterday.get(row.code, 0) + row.yd_quantity

    bought = bought_today(trades, unit_shares, cost_rule)
    sales = await settled_sales(datetime.fromtimestamp(0, UTC).date(), datetime.now(UTC).date(), session)
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


async def reread(trade: Trade, session: ShioajiSession, logger: ILoggingProvider) -> Trade:
    """
    One read of the exchange order's status. Returns the freshest copy: the one list_trades holds as the same exchange
    order (is_exchange_order), else `trade` itself, also when the read fails.
    """
    try:
        await sdk_request(session, session.client.update_status, trade=trade)
        listed = await sdk_request(session, session.client.list_trades)

    except Exception as error:
        logger.warning(f"Shioaji status refresh failed: {error}")
        return trade

    return next((known for known in listed if is_exchange_order(known, trade.contract.code, trade.order, logger)), trade)


async def refreshed(
    trade: Trade, session: ShioajiSession, unit_shares: UnitShares, waits: Waits, stop: Event | None, logger: ILoggingProvider
) -> Trade:
    """
    Reads the exchange order at once, then after each of `waits`, until it is done, and returns the freshest copy.
    `stop` set ends the waits, never a read in flight. A failed read counts as one read.
    """
    for index, seconds in enumerate([0.0, *waits]):
        if index and await stopped_within(stop, seconds):
            break

        trade = await reread(trade, session, logger)

        if not exchange_order_of(trade, unit_shares).status.is_open:
            break

    return trade


async def concluded(
    trade: Trade,
    waits: Waits,
    stop: Event,
    session: ShioajiSession,
    unit_shares: UnitShares,
    shioaji: ShioajiConfig,
    logger: ILoggingProvider,
) -> Trade:
    """
    The exchange order once the adapter is through with it: read as `waits` says and, when still working then or once
    `stop` is set, cancelled and read again.
    """
    logger.info(f"Shioaji order {trade.order.custom_field}: sent, read until done or for {math.fsum(waits):.1f} s")
    trade = await refreshed(trade, session, unit_shares, waits, stop, logger)

    if not exchange_order_of(trade, unit_shares).status.is_open:
        return trade

    if stop.is_set():
        logger.info(f"Shioaji order {trade.order.custom_field}: the run was cancelled, so what still works of it is cancelled")

    return await cancelled(trade, session, unit_shares, shioaji, logger)


async def cancelled(
    trade: Trade, session: ShioajiSession, unit_shares: UnitShares, shioaji: ShioajiConfig, logger: ILoggingProvider
) -> Trade:
    """
    Asks the broker to cancel a working exchange order, then reads it as a board-lot part is read, whatever the run's
    stop says, within shioaji.cancel_timeout_seconds in all. Past them, the copy read before the cancel stands, still
    working, so the order stays UNCONFIRMED for the broker's record of the day to settle, and shutdown stays within the
    server's stop grace (compose.yml).
    """
    tag = trade.order.custom_field

    try:
        async with asyncio.timeout(shioaji.cancel_timeout_seconds):
            try:
                await sdk_request(session, session.client.cancel_order, trade)

            except Exception as error:
                logger.error(f"Shioaji cancel of the order tagged {tag} failed: {error}")

            return await refreshed(trade, session, unit_shares, board_lot_waits(shioaji), None, logger)

    except TimeoutError:
        logger.error(f"Shioaji did not settle the cancel of the order tagged {tag} within {shioaji.cancel_timeout_seconds:g} s")
        return trade


async def listed_trade(
    stock_id: str,
    sent: StockOrder,
    waits: Waits,
    stop: Event,
    session: ShioajiSession,
    timeout_seconds: float,
    logger: ILoggingProvider,
) -> Trade | None:
    """
    The exchange order `sent` for `stock_id`, looked for at once and again after each of `waits` (find_trade): the
    broker may list an order whose answer the SDK stopped waiting for a moment later. The looks take `timeout_seconds`
    in all and end once `stop` is set, so a run cancelled at shutdown stops looking within the server's stop grace
    (compose.yml). None while the broker does not list it then: the order stays UNCONFIRMED for its settlement.
    """
    try:
        async with asyncio.timeout(timeout_seconds):
            for index, seconds in enumerate([0.0, *waits]):
                if index and await stopped_within(stop, seconds):
                    return None

                if (trade := await find_trade(stock_id, sent, session, round(timeout_seconds * 1000), logger)) is not None:
                    return trade

    except TimeoutError:
        logger.warning(f"Shioaji did not list the order tagged {sent.custom_field} within {timeout_seconds:g} s")

    return None


async def find_trade(
    stock_id: str, sent: StockOrder, session: ShioajiSession, timeout_milliseconds: int, logger: ILoggingProvider
) -> Trade | None:
    """
    The exchange order `sent` for `stock_id` (is_exchange_order), after re-reading the account's orders, which may take
    `timeout_milliseconds` on a day of many orders (todays_trades). None when absent or the read fails.
    """
    stock_account = session.client.stock_account

    if stock_account is None:
        return None

    try:
        await sdk_request(session, session.client.update_status, account=stock_account, timeout=timeout_milliseconds)
        listed = await sdk_request(session, session.client.list_trades)

    except Exception as error:
        logger.error(f"Shioaji lookup of the order tagged {sent.custom_field} failed: {error}")
        return None

    return next((trade for trade in listed if is_exchange_order(trade, stock_id, sent, logger)), None)


def exchange_order_of(trade: Trade, unit_shares: UnitShares) -> ExchangeOrder:
    """
    The exchange order in the domain's terms.

    Shares are the order's units times the shares in one unit of its lot; the fill price is the deals'
    volume_weighted_price, which a settlement records too (unrecorded_fills).
    """
    broker_order = trade.order

    if not isinstance(broker_order, StockOrder):
        raise RuntimeError(f"Shioaji trade {broker_order.custom_field} is not a stock order")

    shares_per_unit = unit_shares[broker_order.order_lot]
    deals = trade.status.deals or []
    dealt_units = sum(deal.quantity for deal in deals)
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
        fill_price=volume_weighted_price([(deal.price, deal.quantity) for deal in deals]),
        description=f"{text} (status {trade.status.status_code})" if trade.status.msg else text,
    )


def refusal_for(
    order: Order, contract: object, account: Account, acceptance_rule: OrderAcceptanceRule, lot_split_rule: LotSplitRule
) -> tuple[RejectReason, str] | None:
    """
    Why this broker will not take `order` from `account`, or None: a stock without a stock `contract` first. Checked
    before anything is sent.
    """
    if not isinstance(contract, StockContract):
        return RejectReason.BROKER_REFUSED, f"Shioaji has no stock contract {order.stock_id}"

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
