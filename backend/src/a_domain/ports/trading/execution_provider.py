from asyncio import Event
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Protocol

from a_domain.model.trading.account import Account, BrokerageStatement, Position
from a_domain.model.trading.order import Order
from a_domain.rules.trading.execution import ExchangeOrder
from a_domain.rules.trading.order_rule import BrokerLink
from a_domain.types.enums import LotKind, RejectReason

type SendRefusal = Callable[[], Awaitable[tuple[RejectReason, str] | None]]
"""Why an exchange order may not go out at this moment, or None: what a broker asks right before it sends each one."""


class IExecutionProvider(Protocol):
    """
    A broker: accepts or refuses orders and reports the account. It writes no app records.

    place_order takes a PENDING order and returns it final: REJECTED (a pre-trade rule refused it),
    FILLED, CANCELLED (accepted, then not or not fully filled; any partial fill is recorded) or
    FAILED (technical error). The app sends IOC orders and keeps no working orders.
    """

    async def connect(self) -> None:
        """
        Readies the broker before the first order or account read: the mock seeds its book, Shioaji checks the account
        on the login the realtime quotes hold and activates its certificate. Raises saying what failed.
        """
        ...

    def link(self) -> BrokerLink:
        """Which broker this is and, for a real one, whether its login is up now and on which server. Read right before each send."""
        ...

    async def place_order(self, order: Order, refusal_now: SendRefusal, stop: Event) -> Order:
        """
        Sends `order`, asking `refusal_now` right before each exchange order it sends. A refusal sends nothing more: the
        order is REJECTED with it when nothing went out, and otherwise ends with what the parts already sent did.

        `stop` set (the run was cancelled) ends any wait for an exchange order already sent: what still works of it is
        cancelled at the broker and what it dealt is read. A call to the broker in flight is never interrupted.
        """
        ...

    async def get_account(self) -> Account:
        """Cash and positions, read together."""
        ...

    async def open_positions(self) -> list[Position]:
        """
        The positions alone, in one read: the mock account's book, or the long cash positions a real broker lists, in
        shares at their cost, each marked with the broker's last price and the unrealized PnL the broker computes;
        without a mark where the broker gives no last price.
        """
        ...


class ISimulatedExecutionProvider(IExecutionProvider, Protocol):
    """A broker simulator that keeps the account's book itself and fills orders against it."""

    async def fill(self, order: Order, account: Account, now: datetime) -> None:
        """
        Executes a SUBMITTED order in the simulated market against `account`. The book is saved before the order
        records the fill, so an order whose fill could not be saved is still SUBMITTED.
        """
        ...

    async def reset(self, initial_cash: float, now: datetime) -> Account:
        """
        Opens the book again in one transaction: every position gone, the cash and the cash it opened with set to
        `initial_cash`, and its opening at `now`. Returns the account as it now stands.
        """
        ...


class IBrokerExecutionProvider[Contract, Trade](IExecutionProvider, Protocol):
    """
    A real broker reached through its SDK client. Contract is the SDK's stock contract and Trade its record of one
    exchange order. An order goes to the exchange as one exchange order per lot part. A failed call of the SDK says
    only the error's type and the server's status.
    """

    async def statement(self, sales_from: date, today: date) -> BrokerageStatement:
        """
        The account as the broker reports it now: the bank balance, the settlements due, the positions, today's deals
        and the sales from `sales_from` to `today`. It sends no order and changes nothing at the broker.
        """
        ...

    async def send(
        self, contract: Contract, order: Order, held: Position | None, refusal_now: SendRefusal, stop: Event
    ) -> tuple[list[ExchangeOrder], tuple[RejectReason, str] | None]:
        """
        Sends the order as one exchange order per lot part, in turn, asking `refusal_now` right before each, and records
        what each part dealt on it. Stops at a part still working and at a refusal. Returns the report of every part it
        sent, and the refusal that stopped it before a part, if one did. `stop` as place_order says.
        """
        ...

    async def place(self, contract: Contract, order: Order, lot: LotKind, shares: int, index: int) -> Trade:
        """Places one exchange order. When the confirmation is lost, finds it by its tag, or raises saying to check the broker."""
        ...
