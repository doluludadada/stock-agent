from datetime import datetime
from typing import Protocol

from a_domain.model.trading.account import Account, Position
from a_domain.model.trading.order import ExchangeOrder, Order
from a_domain.types.enums import LotKind, RejectReason


class IExecutionProvider(Protocol):
    """
    A broker: accepts or refuses orders and reports the account. It writes no app records.

    place_order takes a PENDING order and returns it final: REJECTED (a pre-trade rule refused it),
    FILLED, CANCELLED (accepted, then not or not fully filled; any partial fill is recorded) or
    FAILED (technical error). The app sends IOC orders and keeps no working orders.
    """

    async def connect(self) -> None:
        """Opens the broker session before the first order or account read. Raises saying what failed."""
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


class IBrokerExecutionProvider[BrokerAccount, Contract, Trade](IExecutionProvider, Protocol):
    """
    A real broker reached through its SDK client. BrokerAccount is the SDK's stock account, Contract its stock contract
    and Trade its record of one exchange order. An order goes to the exchange as one exchange order per lot part.
    """

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
