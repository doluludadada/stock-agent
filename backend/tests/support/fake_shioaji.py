"""
The subset of shioaji.Shioaji (1.3.1) that ShioajiExecutionProvider calls, without the network.

Method signatures and defaults are copied from shioaji/shioaji.py, and every value it returns is the library's
own model (Trade, OrderStatus, Deal, StockPosition, AccountBalance, SettlementV1, StockAccount, Stock), so the
adapter reads exactly the shapes the real client hands it. A test scripts what the broker reports.
"""

import datetime
from dataclasses import dataclass, field

from shioaji.account import Account, StockAccount
from shioaji.constant import Action, Exchange, Status, StockOrderCond, StockOrderLot, Unit
from shioaji.contracts import Contract, Stock
from shioaji.order import Deal, Order, OrderStatus, Trade
from shioaji.position import AccountBalance, SettlementV1, StockPosition

DONE = {Status.Filled, Status.Cancelled, Status.Failed, Status.Inactive}


@dataclass(frozen=True)
class Report:
    """One answer of update_status: the status and every deal so far, as (price, quantity in the order's unit)."""

    status: Status
    deals: tuple[tuple[float, int], ...] = ()
    msg: str = ""
    deal_quantity: int | None = None
    """What OrderStatus.deal_quantity says; unset, the sum of the deals."""


def stock(code: str, reference: float = 100.0) -> Stock:
    return Stock(
        exchange=Exchange.TSE,
        code=code,
        symbol=f"TSE{code}",
        name=code,
        unit=1000,
        reference=reference,
        limit_up=round(reference * 1.1, 2),
        limit_down=round(reference * 0.9, 2),
    )


def position(code: str, shares: int, price: float, direction: Action = Action.Buy, cond: StockOrderCond = StockOrderCond.Cash):
    return StockPosition(
        id=0,
        code=code,
        direction=direction,
        quantity=shares,
        price=price,
        last_price=price,
        pnl=0.0,
        yd_quantity=shares,
        cond=cond,
        margin_purchase_amount=0,
        collateral=0,
        short_sale_margin=0,
        interest=0,
    )


class FakeStocks:
    """Contracts.Stocks: indexing by code returns the contract, or None for an unknown code like the library."""

    def __init__(self, contracts: dict[str, Stock]) -> None:
        self._contracts = contracts

    def __getitem__(self, code: str) -> Stock | None:
        return self._contracts.get(code)


@dataclass
class FakeContracts:
    Stocks: FakeStocks


@dataclass
class FakeShioaji:
    simulation: bool = True

    account_at_login: StockAccount | None = field(
        default_factory=lambda: StockAccount(
            person_id="A123456789", broker_id="9A95", account_id="0012345", signed=True, username="tester"
        )
    )
    login_error: Exception | None = None
    ca_activates: bool = True
    ca_error: Exception | None = None

    balance: AccountBalance = field(default_factory=lambda: AccountBalance(acc_balance=1_000_000.0, date="2026-10-19", errmsg=""))
    settlement_amounts: tuple[float, float, float] = (0.0, 0.0, 0.0)
    """Settlement amounts due on T, T+1 and T+2; negative is a payment."""
    holdings: list[StockPosition] = field(default_factory=list)
    Contracts: FakeContracts = field(default_factory=lambda: FakeContracts(FakeStocks({"2330": stock("2330")})))

    scripts: dict[StockOrderLot, list[Report]] = field(default_factory=dict)
    """What update_status reports, in turn, for the next order of each lot. Unscripted: filled at its price on the first refresh."""
    honours_cancel: bool = True
    place_error: Exception | None = None
    place_error_after_accepting: bool = False
    updates_in_place: bool = True
    """False: place_order returns a copy, and update_status refreshes only the trade that list_trades holds."""

    stock_account: StockAccount | None = None
    logins: list[dict] = field(default_factory=list)
    logouts: int = 0
    ca_activations: list[dict] = field(default_factory=list)
    placed: list[Trade] = field(default_factory=list)
    cancelled: list[Trade] = field(default_factory=list)
    position_units: list[Unit] = field(default_factory=list)
    _queued: dict[str, list[Report]] = field(default_factory=dict)

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

        if self.login_error is not None:
            raise self.login_error

        self.stock_account = self.account_at_login
        return [self.stock_account] if self.stock_account else []

    def logout(self) -> bool:
        self.logouts += 1
        return True

    def activate_ca(self, ca_path: str, ca_passwd: str, person_id: str = "", store: int = 0) -> bool:
        self.ca_activations.append({"ca_path": ca_path, "ca_passwd": ca_passwd, "person_id": person_id})

        if self.ca_error is not None:
            raise self.ca_error

        return self.ca_activates

    def place_order(self, contract: Contract, order: Order, timeout: int = 5000, cb=None) -> Trade:
        if self.place_error is not None and not self.place_error_after_accepting:
            raise self.place_error

        if not order.account:
            order.account = self.stock_account

        order.seqno = f"{len(self.placed):06d}"
        trade = Trade(
            contract, order, OrderStatus(id=order.seqno, status=Status.PendingSubmit, order_quantity=order.quantity, deals=[])
        )
        self.placed.append(trade)
        self._queued[order.seqno] = list(self.scripts.get(order.order_lot, [Report(Status.Filled, ((order.price, order.quantity),))]))

        if self.place_error is not None:
            raise self.place_error

        return trade if self.updates_in_place else trade.model_copy(deep=True)

    def update_status(self, account: Account = None, trade: Trade = None, timeout: int = 5000, cb=None) -> None:
        seqnos = {trade.order.seqno} if trade else {known.order.seqno for known in self.placed if known.order.account == account}
        cancel_requested = {cancelled.order.seqno for cancelled in self.cancelled}

        for known in [known for known in self.placed if known.order.seqno in seqnos]:
            queued = self._queued[known.order.seqno]

            if queued:
                self._report(known, queued.pop(0))

            elif known.order.seqno in cancel_requested and known.status.status not in DONE and self.honours_cancel:
                self._report(known, Report(Status.Cancelled, tuple((deal.price, deal.quantity) for deal in known.status.deals)))

    def cancel_order(self, trade: Trade, timeout: int = 5000, cb=None) -> Trade:
        self.cancelled.append(trade)
        self._queued[trade.order.seqno].clear()
        return trade

    def list_trades(self) -> list[Trade]:
        return list(self.placed)

    def list_positions(self, account: Account = None, unit: Unit = Unit.Common, timeout: int = 5000, cb=None) -> list[StockPosition]:
        self.position_units.append(unit)
        lots = unit == Unit.Common
        return [row.model_copy(update={"quantity": row.quantity // 1000}) if lots else row.model_copy() for row in self.holdings]

    def account_balance(self, timeout: int = 5000, cb=None) -> AccountBalance:
        return self.balance

    def settlements(self, account: Account = None, timeout: int = 5000, cb=None) -> list[SettlementV1]:
        today = datetime.date(2026, 10, 19)
        return [
            SettlementV1(date=today + datetime.timedelta(days=offset), amount=amount, T=offset)
            for offset, amount in enumerate(self.settlement_amounts)
        ]

    def _report(self, trade: Trade, report: Report) -> None:
        trade.status.status = report.status
        trade.status.msg = report.msg
        trade.status.deals = [
            Deal(seq=str(index), price=price, quantity=quantity, ts=0.0) for index, (price, quantity) in enumerate(report.deals)
        ]
        dealt = sum(quantity for _, quantity in report.deals)
        trade.status.deal_quantity = dealt if report.deal_quantity is None else report.deal_quantity
