"""
The subset of shioaji.Shioaji (1.3.1) that ShioajiExecutionProvider and ShioajiQuoteProvider call, without the network.

Method signatures and defaults are copied from shioaji/shioaji.py, and every value it returns is the library's
own model (Trade, OrderStatus, Deal, StockPosition, AccountBalance, SettlementV1, StockAccount, Stock), so the
adapter reads exactly the shapes the real client hands it. A test scripts what the broker reports.
"""

import datetime
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import c_infrastructure.trading.shioaji.sdk_reporting  # noqa: F401

# isort: split
from shioaji.account import Account, StockAccount
from shioaji.constant import Action, ChangeType, Exchange, OrderState, Status, StockOrderCond, StockOrderLot, TickType, Unit
from shioaji.contracts import Contract, Index, Stock
from shioaji.data import Snapshot
from shioaji.order import Deal, Order, OrderStatus, Trade
from shioaji.position import AccountBalance, SettlementV1, StockPosition, StockProfitLoss, TradingLimits

from c_infrastructure.market.shioaji_quote_provider import ShioajiConnection

DONE = {Status.Filled, Status.Cancelled, Status.Failed, Status.Inactive}


@dataclass(frozen=True)
class Report:
    """One answer of update_status: the status and every deal so far, as (price, quantity in the order's unit)."""

    status: Status
    deals: tuple[tuple[float, int], ...] = ()
    msg: str = ""
    status_code: str = ""
    deal_quantity: int | None = None
    """What OrderStatus.deal_quantity says; unset, the sum of the deals."""


@dataclass(frozen=True)
class OddLotMatches:
    """
    The intraday odd-lot session's call auctions: the first at `first`, then every `interval`. An odd-lot order deals
    at these only, so it takes its script's next report at each one that runs after it was placed, and none before.
    """

    first: datetime.datetime
    interval: datetime.timedelta

    def between(self, placed: datetime.datetime, now: datetime.datetime) -> int:
        """How many matches ran after `placed` and by `now`."""
        if now < self.first:
            return 0

        before = -1 if placed < self.first else (placed - self.first) // self.interval
        return (now - self.first) // self.interval - before


def order_event(contract: Contract, order: Order) -> dict:
    """An order event as Solace sends it for a new order: the account and the login's person id included."""
    account = order.account
    return {
        "operation": {"op_type": "New", "op_code": "00", "op_msg": f"accepted for {account.person_id if account else ''}"},
        "order": {
            "seqno": order.seqno,
            "account": account.model_dump() if account else {},
            "action": order.action.value,
            "price": order.price,
            "quantity": order.quantity,
            "order_lot": order.order_lot.value,
            "custom_field": order.custom_field,
        },
        "contract": {"code": contract.code},
    }


def deal_event(trade: Trade, price: float, quantity: int) -> dict:
    """A deal event as Solace sends it: the account's ids included."""
    order = trade.order
    account = order.account
    return {
        "seqno": order.seqno,
        "account_id": account.account_id if account else "",
        "broker_id": account.broker_id if account else "",
        "action": order.action.value,
        "code": trade.contract.code,
        "order_lot": order.order_lot.value,
        "price": price,
        "quantity": quantity,
        "custom_field": order.custom_field,
    }


def call_back(order_callback: Callable[[OrderState, dict], None] | None, state: OrderState, event: dict) -> None:
    """What the SDK does with each order and deal event: calls the order callback, from a thread of its own."""
    if order_callback is not None:
        caller = threading.Thread(target=order_callback, args=(state, event))
        caller.start()
        caller.join()


def stock(code: str, reference: float = 100.0, updated_on: datetime.date | None = None) -> Stock:
    """
    A stock's contract, its price band 10% each side of `reference`, as of `updated_on` (update_date, YYYY/MM/DD as the
    SDK's contracts of 2026-11-13 hold it). Unset, the contract names no day, as one the adapter takes for an older band.
    """
    return Stock(
        exchange=Exchange.TSE,
        code=code,
        symbol=f"TSE{code}",
        name=code,
        unit=1000,
        reference=reference,
        limit_up=round(reference * 1.1, 2),
        limit_down=round(reference * 0.9, 2),
        update_date=f"{updated_on:%Y/%m/%d}" if updated_on is not None else "",
    )


def position(
    code: str,
    shares: int,
    price: float,
    direction: Action = Action.Buy,
    cond: StockOrderCond = StockOrderCond.Cash,
    held_yesterday: int | None = None,
):
    """A row of list_positions. `held_yesterday` is its yd_quantity, the shares at yesterday's close: unset, all of them."""
    return StockPosition(
        id=0,
        code=code,
        direction=direction,
        quantity=shares,
        price=price,
        last_price=price,
        pnl=0.0,
        yd_quantity=shares if held_yesterday is None else held_yesterday,
        cond=cond,
        margin_purchase_amount=0,
        collateral=0,
        short_sale_margin=0,
        interest=0,
    )


def sale(code: str, shares: int, price: float, pnl: float, day: str) -> StockProfitLoss:
    """A sale the broker settled on `day` (YYYY-MM-DD), with the profit or loss the broker says it realized."""
    return StockProfitLoss(
        id=0,
        code=code,
        quantity=shares,
        pnl=pnl,
        date=day,
        dseq="A0001",
        price=price,
        pr_ratio=0.0,
        cond=StockOrderCond.Cash,
        seqno="1",
    )


def snapshot(code: str, traded_at: datetime.datetime, close: float, total_volume: int, change: float = 0.0) -> Snapshot:
    """
    One stock's snapshot as Shioaji serves it: stamped with the last trade's Taipei wall-clock time as nanoseconds since
    the epoch read as UTC, volumes in board lots. Measured on 2026-11-06 after the session: 2330 at 14:30:00 (its
    after-hours fixed-price trade), 2135.0, 97065 lots.
    """
    wall_clock = traded_at.replace(tzinfo=datetime.UTC)
    return Snapshot(
        ts=int(wall_clock.timestamp()) * 1_000_000_000 + wall_clock.microsecond * 1_000,
        code=code,
        exchange="TSE",
        open=close,
        high=close,
        low=close,
        close=close,
        tick_type=TickType.Sell,
        change_price=change,
        change_rate=0.0,
        change_type=ChangeType.Unchanged,
        average_price=close,
        volume=1 if total_volume else 0,
        total_volume=total_volume,
        amount=0,
        total_amount=0,
        yesterday_volume=0.0,
        buy_price=close,
        buy_volume=1.0,
        sell_price=close,
        sell_volume=1,
        volume_ratio=0.0,
    )


class FakeStocks:
    """Contracts.Stocks: indexing by code returns the contract, or None for an unknown code like the library."""

    def __init__(self, contracts: dict[str, Stock] | dict[str, Index]) -> None:
        self._contracts = contracts

    def __getitem__(self, code: str) -> Stock | Index | None:
        return self._contracts.get(code)


class FakeIndexs:
    """
    Contracts.Indexs: indexing by exchange returns that exchange's indexes, which index by symbol or code, and None for
    an unknown one like the library. As Shioaji 1.3.1 lists them: the TAIEX is TSE001, code 001, on TSE.
    """

    def __init__(self, contracts: dict[str, dict[str, Index]] | None = None) -> None:
        taiex = Index(exchange=Exchange.TSE, code="001", symbol="TSE001", name="加權指數")
        self._contracts = {"TSE": {"TSE001": taiex, "001": taiex}} if contracts is None else contracts

    def __getitem__(self, exchange: str) -> FakeStocks | None:
        return FakeStocks(self._contracts[exchange]) if exchange in self._contracts else None


@dataclass
class FakeContracts:
    Stocks: FakeStocks
    Indexs: FakeIndexs = field(default_factory=FakeIndexs)


@dataclass
class FakeShioaji:
    simulation: bool = True
    """
    True: the simulation server, which answers the balance with 0 and no error and lists no settlement, as measured on
    2026-11-17, whatever `balance` and `settlement_amounts` say. False: the production server, which reports both.
    """

    account_at_login: StockAccount | None = field(
        default_factory=lambda: StockAccount(
            person_id="A123456789", broker_id="9A95", account_id="0012345", signed=True, username="tester"
        )
    )
    login_error: Exception | None = None
    login_gate: threading.Event | None = None
    """When set, a login waits in its thread until the test sets the event, as a slow server keeps it waiting."""
    ca_activates: bool = True
    ca_error: Exception | None = None

    balance: AccountBalance = field(default_factory=lambda: AccountBalance(acc_balance=1_000_000.0, date="2026-10-19", errmsg=""))
    settlement_amounts: tuple[float, float, float] = (0.0, 0.0, 0.0)
    """Settlement amounts due on T, T+1 and T+2; negative is a payment."""
    trading_available: int = 0
    """
    What trading_limits answers the stock account may still buy today. 0, every figure 0, is what the simulation server
    answered on 2026-11-19; a production login answers its limit.
    """
    holdings: list[StockPosition] = field(default_factory=list)
    profit_losses: list[StockProfitLoss] = field(default_factory=list)
    """The sales the broker settled, each with its date: list_profit_loss answers those within the dates asked."""
    Contracts: FakeContracts = field(default_factory=lambda: FakeContracts(FakeStocks({"2330": stock("2330")})))

    scripts: dict[StockOrderLot, list[Report]] = field(default_factory=dict)
    """What update_status reports, in turn, for the next order of each lot. Unscripted: filled at its price on the first refresh."""
    honours_cancel: bool = True
    clock: Callable[[], datetime.datetime] | None = None
    """The test's clock: set, each place_order and cancel_order is stamped with it in placed_at and cancelled_at."""
    odd_lot_matches: OddLotMatches | None = None
    """Set, with `clock`: an odd-lot order's script moves at the session's matches instead of at each status read."""
    place_error: Exception | None = None
    place_error_after_accepting: bool = False
    place_error_lot: StockOrderLot | None = None
    """Set: only an order of this lot raises place_error, as the odd-lot part's answer alone may be lost."""
    unlisted_refreshes: int = 0
    """
    With place_error_after_accepting: how many account-wide update_status calls after the send leave the order out of
    list_trades, as SinoPac listed 3029 about a second after the adapter's one lookup on 2026-11-19. It deals meanwhile.
    """
    place_gate: threading.Event | None = None
    """When set, place_order waits in its thread, the order already at the broker, until the test sets the event."""
    status_gate: threading.Event | None = None
    """When set, update_status after a cancel request waits in its thread until the test sets the event, unanswered."""
    refusals: dict[str, Exception] = field(default_factory=dict)
    """What each named method of the account and its orders raises instead of answering, as the SDK does for a server's refusal."""
    refuses_once_placed: bool = False
    """True: the refusals start once an order was placed, so the account read before it still answers."""
    updates_in_place: bool = True
    """False: place_order returns a copy, and update_status refreshes only the trade that list_trades holds."""
    account_refresh_milliseconds: int = 0
    """
    How long the server takes to refresh every order of the account today. An account-wide update_status that may wait
    less raises TimeoutError, as the SDK did on 2026-11-18 for an account of about 40 orders at its 5 s default.
    """
    account_refreshes: list[int] = field(default_factory=list)
    """The timeout, in milliseconds, of each account-wide update_status the server answered or timed out."""
    account_refresh_seconds: float = 0.0
    """Real seconds each account-wide update_status keeps its thread waiting before it answers, as a slow server does."""

    market_data_error: Exception | None = None
    """What snapshots raises instead of answering, as the SDK does for a server's refusal."""
    refused_codes: frozenset[str] = frozenset()
    """A snapshots request that names one of these codes raises after it is counted, as a server that refuses a contract would."""
    session_down_callback: Callable[[], None] | None = None
    """The one callback the SDK keeps: a second registration replaces the first."""
    order_callback: Callable[[OrderState, dict], None] | None = None
    """What the SDK calls with each order and deal event; unset, the SDK prints the whole event to stdout."""
    snapshot_answers: dict[str, Snapshot] = field(default_factory=dict)
    """What snapshots answers for each code; a code without one gets no snapshot."""
    snapshot_requests: list[list[str]] = field(default_factory=list)

    stock_account: StockAccount | None = None
    logins: list[dict] = field(default_factory=list)
    logouts: int = 0
    ca_activations: list[dict] = field(default_factory=list)
    placed: list[Trade] = field(default_factory=list)
    cancelled: list[Trade] = field(default_factory=list)
    placed_at: list[datetime.datetime] = field(default_factory=list)
    cancelled_at: list[datetime.datetime] = field(default_factory=list)
    position_units: list[Unit] = field(default_factory=list)
    profit_loss_requests: list[tuple[str, str, Unit]] = field(default_factory=list)
    bank_reads: list[str] = field(default_factory=list)
    """Each read of the bank balance and of the settlements, which only a production account has."""
    _queued: dict[str, list[Report]] = field(default_factory=dict)
    _matched: dict[str, int] = field(default_factory=dict)
    _unlisted: dict[str, int] = field(default_factory=dict)

    def login(
        self,
        api_key: str,
        secret_key: str,
        fetch_contract: bool = True,
        contracts_timeout: int = 0,
        contracts_cb=None,
        subscribe_trade: bool = True,
        receive_window: int = 30000,
    ) -> list[Account]:
        self.logins.append({"api_key": api_key, "secret_key": secret_key, "subscribe_trade": subscribe_trade})

        if self.login_gate is not None:
            self.login_gate.wait(timeout=5)

        if self.login_error is not None:
            raise self.login_error

        self.stock_account = self.account_at_login
        return [self.stock_account] if self.stock_account else []

    def set_session_down_callback(self, func: Callable[[], None]) -> None:
        self.session_down_callback = func

    def set_order_callback(self, func: Callable[[OrderState, dict], None]) -> None:
        self.order_callback = func

    def session_down(self) -> None:
        """What Solace does once its reconnects gave up: calls the session-down callback, from a thread of its own."""
        if self.session_down_callback is not None:
            caller = threading.Thread(target=self.session_down_callback)
            caller.start()
            caller.join()

    def snapshots(self, contracts: list[Contract], timeout: int = 30000, cb=None) -> list[Snapshot]:
        assert len(self.logins) > self.logouts, "snapshots outside a login"

        if self.market_data_error is not None:
            raise self.market_data_error
        self.snapshot_requests.append([contract.code for contract in contracts])

        if self.refused_codes & {contract.code for contract in contracts}:
            raise TimeoutError("the server did not answer a contract of this request")

        return [self.snapshot_answers[contract.code] for contract in contracts if contract.code in self.snapshot_answers]

    def logout(self) -> bool:
        self.logouts += 1
        return True

    def activate_ca(self, ca_path: str, ca_passwd: str, person_id: str = "", store: int = 0) -> bool:
        self.ca_activations.append({"ca_path": ca_path, "ca_passwd": ca_passwd, "person_id": person_id})

        if self.ca_error is not None:
            raise self.ca_error

        return self.ca_activates

    def place_order(self, contract: Contract, order: Order, timeout: int = 5000, cb=None) -> Trade:
        error = self.place_error if self.place_error_lot in (None, order.order_lot) else None

        if error is not None and not self.place_error_after_accepting:
            raise error

        if not order.account:
            order.account = self.stock_account

        order.seqno = f"{len(self.placed):06d}"
        trade = Trade(
            contract, order, OrderStatus(id=order.seqno, status=Status.PendingSubmit, order_quantity=order.quantity, deals=[])
        )
        self.placed.append(trade)
        self._stamp(self.placed_at)
        self._queued[order.seqno] = list(self.scripts.get(order.order_lot, [Report(Status.Filled, ((order.price, order.quantity),))]))
        call_back(self.order_callback, OrderState.StockOrder, order_event(contract, order))

        if self.place_gate is not None:
            self.place_gate.wait(timeout=5)

        if error is not None:
            self._unlisted[order.seqno] = self.unlisted_refreshes
            raise error

        return trade if self.updates_in_place else trade.model_copy(deep=True)

    def update_status(self, account: Account = None, trade: Trade = None, timeout: int = 5000, cb=None) -> None:
        self._fail_if_told("update_status")

        if trade is None:
            self.account_refreshes.append(timeout)
            time.sleep(self.account_refresh_seconds)

            if self.account_refresh_milliseconds > timeout:
                raise TimeoutError("the server did not refresh the account's orders in time")

            self._unlisted = {seqno: left - 1 for seqno, left in self._unlisted.items() if left}

        seqnos = {trade.order.seqno} if trade else {known.order.seqno for known in self.placed if known.order.account == account}
        cancel_requested = {cancelled.order.seqno for cancelled in self.cancelled}

        if cancel_requested and self.status_gate is not None:
            self.status_gate.wait(timeout=5)

        for known in [known for known in self.placed if known.order.seqno in seqnos]:
            queued, due = self._queued[known.order.seqno], self._reports_due(known)

            if queued and due:
                report = queued[min(due, len(queued)) - 1]
                del queued[:due]
                self._report(known, report)

            elif known.order.seqno in cancel_requested and known.status.status not in DONE and self.honours_cancel:
                self._report(known, Report(Status.Cancelled, tuple((deal.price, deal.quantity) for deal in known.status.deals)))

    def cancel_order(self, trade: Trade, timeout: int = 5000, cb=None) -> Trade:
        self._fail_if_told("cancel_order")
        self.cancelled.append(trade)
        self._stamp(self.cancelled_at)
        self._queued[trade.order.seqno].clear()
        return trade

    def list_trades(self) -> list[Trade]:
        self._fail_if_told("list_trades")
        return [trade for trade in self.placed if trade.order.seqno not in self._unlisted]

    def list_positions(self, account: Account = None, unit: Unit = Unit.Common, timeout: int = 5000, cb=None) -> list[StockPosition]:
        self._fail_if_told("list_positions")
        self.position_units.append(unit)
        lots = unit == Unit.Common
        return [row.model_copy(update={"quantity": row.quantity // 1000}) if lots else row.model_copy() for row in self.holdings]

    def list_profit_loss(
        self, account: Account = None, begin_date: str = "", end_date: str = "", unit: Unit = Unit.Common, timeout: int = 5000, cb=None
    ) -> list[StockProfitLoss]:
        self._fail_if_told("list_profit_loss")
        self.profit_loss_requests.append((begin_date, end_date, unit))
        return [row.model_copy() for row in self.profit_losses if begin_date <= row.date <= end_date]

    def account_balance(self, timeout: int = 5000, cb=None) -> AccountBalance:
        self._fail_if_told("account_balance")
        self.bank_reads.append("account_balance")
        return self.balance.model_copy(update={"acc_balance": 0.0}) if self.simulation else self.balance

    def trading_limits(self, account: Account = None, timeout: int = 5000, cb=None) -> TradingLimits:
        self._fail_if_told("trading_limits")
        self.bank_reads.append("trading_limits")
        limit = self.trading_available
        return TradingLimits(trading_limit=limit, trading_used=0, trading_available=limit)

    def settlements(self, account: Account = None, timeout: int = 5000, cb=None) -> list[SettlementV1]:
        self._fail_if_told("settlements")
        self.bank_reads.append("settlements")

        if self.simulation:
            return []

        today = datetime.date(2026, 10, 19)
        return [
            SettlementV1(date=today + datetime.timedelta(days=offset), amount=amount, T=offset)
            for offset, amount in enumerate(self.settlement_amounts)
        ]

    def _stamp(self, times: list[datetime.datetime]) -> None:
        if self.clock is not None:
            times.append(self.clock())

    def _reports_due(self, trade: Trade) -> int:
        """One per status read; for an odd-lot order under odd_lot_matches, one per match since the last read."""
        if self.odd_lot_matches is None or trade.order.order_lot != StockOrderLot.IntradayOdd:
            return 1

        assert self.clock is not None, "odd_lot_matches runs on the test's clock"
        seqno = trade.order.seqno
        matches = self.odd_lot_matches.between(self.placed_at[self.placed.index(trade)], self.clock())
        due, self._matched[seqno] = matches - self._matched.get(seqno, 0), matches
        return due

    def _report(self, trade: Trade, report: Report) -> None:
        for price, quantity in report.deals[len(trade.status.deals or []) :]:
            call_back(self.order_callback, OrderState.StockDeal, deal_event(trade, price, quantity))

        trade.status.status = report.status
        trade.status.msg = report.msg
        trade.status.status_code = report.status_code
        trade.status.deals = [
            Deal(seq=str(index), price=price, quantity=quantity, ts=0.0) for index, (price, quantity) in enumerate(report.deals)
        ]
        dealt = sum(quantity for _, quantity in report.deals)
        trade.status.deal_quantity = dealt if report.deal_quantity is None else report.deal_quantity

    def _fail_if_told(self, method: str) -> None:
        if method in self.refusals and (self.placed or not self.refuses_once_placed):
            raise self.refusals[method]


def same_account(earlier: FakeShioaji) -> FakeShioaji:
    """
    The client of a new login on `earlier`'s account. SinoPac keeps the day's orders by account: a new login's
    update_status(account) and list_trades find the orders an earlier client sent and refresh them, and its
    cancel_order cancels them, as the code already relies on after a restart. So the new client shares that record with
    `earlier`, and its contracts and quotes.
    """
    return FakeShioaji(
        earlier.simulation,
        Contracts=earlier.Contracts,
        snapshot_answers=earlier.snapshot_answers,
        placed=earlier.placed,
        _queued=earlier._queued,
        _matched=earlier._matched,
        _unlisted=earlier._unlisted,
    )


def connection_on(client: FakeShioaji) -> ShioajiConnection:
    """A connection whose one login, on `client`, is up, as a runtime finds it once connect_shioaji logged in."""
    return ShioajiConnection(client=client, up_clients={id(client): client})
