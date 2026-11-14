from collections.abc import Callable
from datetime import date, datetime
from typing import Protocol

from a_domain.model.trading.account import Account, BrokerageStatement, BrokerFill, Position
from a_domain.model.trading.order import ExchangeOrder, Order
from a_domain.rules.trading.order_rule import BrokerLink
from a_domain.types.enums import LotKind, RejectReason


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

    async def place_order(self, order: Order) -> Order: ...

    async def get_account(self) -> Account:
        """Cash and positions, read together."""
        ...

    def refusal_for(self, order: Order, account: Account) -> tuple[RejectReason, str] | None:
        """Why this broker will not take `order` from `account`, or None. Checked before anything is sent."""
        ...


class ISimulatedExecutionProvider(IExecutionProvider, Protocol):
    """A broker simulator that keeps the account's book itself and fills orders against it."""

    async def fill(self, order: Order, account: Account, now: datetime) -> None:
        """
        Executes a SUBMITTED order in the simulated market against `account`. The book is saved before the order
        records the fill, so an order whose fill could not be saved is still SUBMITTED.
        """
        ...

    async def save_account(self, account: Account, now: datetime) -> None:
        """Writes the account's cash and positions to the book."""
        ...

    async def reset(self, initial_cash: float, now: datetime) -> Account:
        """
        Opens the book again in one transaction: every position gone, the cash and the cash it opened with set to
        `initial_cash`, and its opening at `now`. Returns the account as it now stands.
        """
        ...


class IBrokerExecutionProvider[BrokerAccount, Contract, Trade](IExecutionProvider, Protocol):
    """
    A real broker reached through its SDK client. BrokerAccount is the SDK's stock account, Contract its stock contract
    and Trade its record of one exchange order. An order goes to the exchange as one exchange order per lot part. Every
    call of the SDK is a request, so its failure says only the error's type and the server's status.
    """

    async def request[**Arguments, Answer](
        self, call: Callable[Arguments, Answer], *args: Arguments.args, **kwargs: Arguments.kwargs
    ) -> Answer:
        """
        Makes one request, `call` with its arguments in a worker thread. Its failure raises RuntimeError saying what the
        broker quote provider's failure_of says of the SDK's error, never the error's text.
        """
        ...

    def stock_account(self) -> BrokerAccount:
        """The SDK's stock account of the login. Raises while the login gave none."""
        ...

    async def statement(self, sales_from: date, today: date) -> BrokerageStatement:
        """
        The account as the broker reports it now: the bank balance, the settlements due, the positions, today's deals
        and the sales from `sales_from` to `today`. It sends no order and changes nothing at the broker.
        """
        ...

    async def open_positions(self) -> list[Position]:
        """
        The long cash positions the broker lists, in shares at their cost, each marked with the broker's last price and
        the unrealized PnL the broker computes; without a mark where the broker gives no last price.
        """
        ...

    async def fills(self, today: date) -> list[BrokerFill]:
        """Every deal of the account's exchange orders the broker lists for today, in shares."""
        ...

    async def sales(self, first: date, last: date) -> list[BrokerFill]:
        """The account's sales the broker settled from `first` to `last`, each with the PnL the broker says it realized."""
        ...

    async def cash(self, broker_account: BrokerAccount) -> float:
        """The cash the account can still pay for a BUY with. Never more than the broker will settle."""
        ...

    async def send(self, contract: Contract, order: Order, held: Position | None) -> list[ExchangeOrder]:
        """
        Sends the order as one exchange order per lot part, in turn, and records what each part dealt on it. Stops at
        a part still working. Returns the report of every part it sent.
        """
        ...

    async def place(self, contract: Contract, order: Order, lot: LotKind, shares: int, index: int) -> Trade:
        """Places one exchange order. When the confirmation is lost, finds it by its tag, or raises saying to check the broker."""
        ...

    async def refresh(self, trade: Trade) -> Trade:
        """Re-reads the exchange order until it is done or the polls run out, and returns the freshest copy."""
        ...

    async def cancel(self, trade: Trade) -> Trade:
        """Asks the broker to cancel a working exchange order, then refreshes it."""
        ...

    async def find_trade(self, tag: str) -> Trade | None:
        """The exchange order with this tag, after re-reading the account's orders. None when absent or the read fails."""
        ...

    def exchange_order_of(self, trade: Trade) -> ExchangeOrder:
        """The exchange order in the domain's terms."""
        ...
