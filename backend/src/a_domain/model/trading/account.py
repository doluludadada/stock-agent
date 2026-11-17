from datetime import date, datetime
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, FiniteFloat, PositiveInt, validate_call
from pydantic.dataclasses import dataclass

from a_domain.types.enums import TradeAction
from a_domain.types.ids import OrderId, RunId
from a_domain.types.values import Fraction, NonEmptyText, NonNegativeFiniteFloat, PositiveFiniteFloat


@dataclass(frozen=True)
class Mark:
    """
    The price a position is valued at and when that price was quoted: a realtime quote, a daily close or a fill price.

    `unrealized_pnl` is what selling the whole position at `price` would bring after the SELL fee and tax, minus its
    cost basis. It is None when the mark was taken without the trading costs: a fill snapshot keeps prices only, and
    SnapshotValueRule values a snapshot again whenever it is shown. A PnL never exists without its price and time.
    """

    price: PositiveFiniteFloat
    at: datetime
    unrealized_pnl: FiniteFloat | None = None


@dataclass(config=ConfigDict(validate_assignment=True))
class Position:
    """
    Broker/account ownership state and, once a rule valued it, the price it is valued at. `average_cost` is per share
    and includes the buy fees paid. A position the broker reports has no mark: AccountValueRule, SnapshotValueRule and
    FillSnapshotRule build new marked positions and never mark one in place.
    """

    stock_id: NonEmptyText
    quantity: PositiveInt
    average_cost: PositiveFiniteFloat

    opened_at: datetime | None = None

    mark: Mark | None = None
    """None: no price is known, so the position counts at its average cost with no unrealized PnL."""

    weight: Fraction | None = None
    """Its market value over the equity of the account AccountValueRule valued it in. None anywhere else."""

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.average_cost

    @property
    def mark_price(self) -> float:
        """The mark's price, else the average cost."""
        return self.mark.price if self.mark else self.average_cost

    @property
    def marked_at(self) -> datetime | None:
        """When the mark's price was quoted. None: no price is known."""
        return self.mark.at if self.mark else None

    @property
    def market_value(self) -> float:
        return self.quantity * self.mark_price

    @property
    def unrealized_pnl(self) -> float:
        """The mark's unrealized PnL. 0 when there is no mark or the mark was taken without the trading costs."""
        return self.mark.unrealized_pnl if self.mark and self.mark.unrealized_pnl is not None else 0.0

    @property
    def unrealized_return(self) -> float | None:
        """The mark's unrealized PnL over the cost basis: 0.1 is 10% up. None where the mark carries no PnL."""
        return None if self.mark is None or self.mark.unrealized_pnl is None else self.mark.unrealized_pnl / self.cost_basis

    @validate_call
    def profit_on_sale(self, quantity: PositiveInt, net_proceeds: FiniteFloat) -> float:
        """Net proceeds of selling `quantity` shares minus their cost basis. The one PnL formula, realized or not."""
        return net_proceeds - quantity * self.average_cost

    @validate_call
    def can_cover(self, quantity: PositiveInt) -> bool:
        return self.quantity >= quantity

    @validate_call
    def add(self, quantity: PositiveInt, price: PositiveFiniteFloat) -> None:
        """Buys more at `price`. The mark and the weight valued the old quantity, so they go."""
        total_quantity = self.quantity + quantity
        self.average_cost = (self.cost_basis + quantity * price) / total_quantity
        self.quantity = total_quantity
        self.mark = None
        self.weight = None

    @validate_call
    def remaining_after_sell(self, quantity: PositiveInt) -> int:
        if not self.can_cover(quantity):
            raise ValueError("Position quantity is insufficient")

        return self.quantity - quantity

    @validate_call
    def reduce(self, quantity: PositiveInt) -> None:
        """Sells `quantity` shares. The mark and the weight valued the old quantity, so they go."""
        self.quantity = self.remaining_after_sell(quantity)
        self.mark = None
        self.weight = None


@dataclass(frozen=True)
class AccountOpening:
    """
    When a mock account opened, at its first read or its last reset, and the cash it opened with. Its account page, the
    equity curve and the trades start there. A real broker reports none.
    """

    initial_cash: NonNegativeFiniteFloat
    opened_at: datetime


@dataclass(config=ConfigDict(validate_assignment=True))
class Account:
    """
    Cash and positions held at the broker.

    Cash settles at the fill: T+2 settlement and margin are not modeled, and there are no pending
    orders (the app sends IOC only). Fees and tax reach the account through the amounts each trade
    settles with, which TradingCostRule computes.

    The account the broker reports has no marks, so its market value counts every position at its average cost.
    AccountValueRule returns the same account valued at the run's latest prices. A run sizes its BUYs on that
    account's equity, which the run keeps as PipelineStatus.equity; menu 7 shows it as the account now.
    """

    account_id: NonEmptyText = "default"

    cash: NonNegativeFiniteFloat = 0.0
    positions: list[Position] = Field(default_factory=list)

    opening: AccountOpening | None = None
    """The mock book's opening. None at a real broker."""

    @property
    def stock_ids(self) -> frozenset[str]:
        """The ids of the stocks this account holds."""
        return frozenset(position.stock_id for position in self.positions)

    @property
    def market_value(self) -> float:
        """Each position at its mark, a position without one at its average cost."""
        return sum(position.market_value for position in self.positions)

    @property
    def unrealized_pnl(self) -> float:
        """Net of the SELL fee and tax, summed over the positions valued with the trading costs."""
        return sum(position.unrealized_pnl for position in self.positions)

    @property
    def equity(self) -> float:
        """Cash plus market value: gross, before the costs of selling."""
        return self.cash + self.market_value

    @property
    def opened_at(self) -> datetime | None:
        """When the mock book opened; None at a real broker, whose history has no start the app knows."""
        return self.opening.opened_at if self.opening else None

    @property
    def profit(self) -> float | None:
        """Equity minus the cash it opened with: the profit or loss since the opening. None without an opening."""
        return None if self.opening is None else self.equity - self.opening.initial_cash

    @validate_call
    def can_afford(self, amount: NonNegativeFiniteFloat) -> bool:
        return self.cash >= amount

    def position_for(self, stock_id: str) -> Position | None:
        for position in self.positions:
            if position.stock_id == stock_id:
                return position

        return None

    @validate_call
    def buy(
        self, stock_id: NonEmptyText, quantity: PositiveInt, price: PositiveFiniteFloat, total_cost: PositiveFiniteFloat
    ) -> Position:
        """Pays `total_cost` (gross plus fee) for shares traded at `price`. The whole cost, fee included, is the cost basis."""
        if total_cost < price * quantity:
            raise ValueError("Total cost cannot be below the traded value")

        if not self.can_afford(total_cost):
            raise ValueError("Insufficient cash")

        position = self.position_for(stock_id)

        if position is None:
            position = Position(stock_id=stock_id, quantity=quantity, average_cost=total_cost / quantity)
            self.positions.append(position)

        else:
            position.add(quantity=quantity, price=total_cost / quantity)

        self.cash -= total_cost

        return position

    @validate_call
    def sell(self, stock_id: NonEmptyText, quantity: PositiveInt, cash_delta: FiniteFloat) -> int:
        """Receives `cash_delta` (gross minus fee and tax) and returns the shares left in the position."""
        if self.cash + cash_delta < 0:
            raise ValueError("Cash delta must keep cash non-negative")

        position = self.position_for(stock_id)

        if position is None:
            raise ValueError(f"Position not found: {stock_id}")

        remaining_quantity = position.remaining_after_sell(quantity)

        if remaining_quantity == 0:
            self.positions.remove(position)

        else:
            position.reduce(quantity)

        self.cash += cash_delta

        return remaining_quantity


@dataclass(frozen=True, kw_only=True)
class AccountSnapshot:
    """
    The account right after a fill: its cash, and each position marked at the price the run had for it then (the
    filled stock at its fill price), without the trading costs. All snapshots in time order are the account's
    history. AccountAsOfRule hands one back with its account valued at a later day's closes; its identity stays the
    fill's.
    """

    snapshot_id: UUID = Field(default_factory=uuid4)
    taken_at: datetime
    run_id: RunId
    order_id: OrderId
    account: Account


@dataclass(frozen=True, kw_only=True)
class Settlement:
    """Cash a real broker settles for the account on one day: negative to pay for purchases, positive to receive from sales."""

    settles_on: date
    amount: FiniteFloat


@dataclass(frozen=True, kw_only=True)
class BrokerFill:
    """
    One execution as a real broker reports it, in shares: a deal of today, or a past sale with the profit or loss the
    broker says it realized, its own fees and tax included.
    """

    stock_id: NonEmptyText
    action: TradeAction
    quantity: PositiveInt
    price: PositiveFiniteFloat
    filled_on: date
    realized_pnl: FiniteFloat | None = None
    """The broker's own figure for a past sale. None for a deal of today, which the broker has not settled yet."""


@dataclass(frozen=True, kw_only=True)
class BrokerageStatement:
    """
    A real broker's account as the broker itself reports it at `read_at`: every figure is the broker's, none computed
    by the app's cost rules, but the balance on the simulation server. It carries no account number, person id or token.
    """

    read_at: datetime
    simulation: bool
    """Whether the login that answered is on the broker's simulation server, which holds no real money."""

    balance: FiniteFloat
    """The bank balance of the account's settlement account. On the simulation server, SimulationCashRule's figure."""

    settlements: list[Settlement]
    positions: list[Position]
    """Each marked with the broker's last price and the unrealized PnL the broker computes for it."""

    fills: list[BrokerFill]
    """Today's deals, newest last as the broker lists them."""

    sales: list[BrokerFill]
    """The past sales from `sales_from` to today, each with its realized PnL."""

    sales_from: date

    @property
    def market_value(self) -> float:
        return sum(position.market_value for position in self.positions)

    @property
    def unrealized_pnl(self) -> float:
        return sum(position.unrealized_pnl for position in self.positions)

    @property
    def realized_pnl(self) -> float:
        """The realized PnL of the sales listed."""
        return sum(sale.realized_pnl or 0.0 for sale in self.sales)
