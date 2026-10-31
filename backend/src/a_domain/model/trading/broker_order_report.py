from dataclasses import dataclass

from a_domain.model.trading.order import ORDER_TRANSITIONS
from a_domain.types.enums import OrderStatus


@dataclass(frozen=True, kw_only=True)
class BrokerOrderReport:
    """
    What a real broker reports about one exchange order, in the domain's terms: its place in the order lifecycle and
    what executed so far, in shares. A domain order goes to the exchange as one exchange order per lot part.
    """

    stock_id: str
    status: OrderStatus
    ordered_shares: int

    dealt_shares: int
    """The shares in the broker's list of deals, which is what an order records as filled."""

    reported_dealt_shares: int
    """The shares the broker's status counts as dealt. More than dealt_shares while deals are still on their way."""

    fill_price: float | None
    """The deals' volume-weighted price. None while nothing is dealt."""

    description: str
    """The broker's own words for the exchange order, for logs and for the reason the order ends with."""

    @property
    def is_done(self) -> bool:
        return not ORDER_TRANSITIONS[self.status]

    @property
    def deals_missing(self) -> bool:
        """The deals cannot be the whole story: fewer than the broker counts, or fewer than a FILLED order's quantity."""
        if self.dealt_shares < self.reported_dealt_shares:
            return True

        return self.status == OrderStatus.FILLED and self.dealt_shares < self.ordered_shares
