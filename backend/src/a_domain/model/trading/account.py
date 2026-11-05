from datetime import datetime
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, FiniteFloat, PositiveInt, validate_call
from pydantic.dataclasses import dataclass

from a_domain.types.ids import OrderId, RunId
from a_domain.types.values import NonEmptyText, NonNegativeFiniteFloat, PositiveFiniteFloat


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

    @validate_call
    def profit_on_sale(self, quantity: PositiveInt, net_proceeds: FiniteFloat) -> float:
        """Net proceeds of selling `quantity` shares minus their cost basis. The one PnL formula, realized or not."""
        return net_proceeds - quantity * self.average_cost

    @validate_call
    def can_cover(self, quantity: PositiveInt) -> bool:
        return self.quantity >= quantity

    @validate_call
    def add(self, quantity: PositiveInt, price: PositiveFiniteFloat) -> None:
        """Buys more at `price`. The mark valued the old quantity, so it goes."""
        total_quantity = self.quantity + quantity
        self.average_cost = (self.cost_basis + quantity * price) / total_quantity
        self.quantity = total_quantity
        self.mark = None

    @validate_call
    def remaining_after_sell(self, quantity: PositiveInt) -> int:
        if not self.can_cover(quantity):
            raise ValueError("Position quantity is insufficient")

        return self.quantity - quantity

    @validate_call
    def reduce(self, quantity: PositiveInt) -> None:
        """Sells `quantity` shares. The mark valued the old quantity, so it goes."""
        self.quantity = self.remaining_after_sell(quantity)
        self.mark = None


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
