from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from icontract import ensure, require

from a_domain.model.trading.broker_order_report import BrokerOrderReport
from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.model.trading.trade_cost import TradeCost
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.types.enums import LotKind, OrderStatus, RejectReason, TradeAction


@dataclass(frozen=True)
class LotSplitRule:
    """
    Splits an order's quantity into what the exchange trades: the whole board lots as one board-lot part and the rest
    as one odd-lot part, each as (kind, shares). With 1000-share lots, 2500 shares are 2000 board-lot shares plus 500
    odd shares.
    """

    board_lot_shares: int

    @require(lambda quantity: quantity > 0)
    @ensure(lambda quantity, result: sum(shares for _, shares in result) == quantity)
    def apply(self, quantity: int) -> list[tuple[LotKind, int]]:
        odd_shares = quantity % self.board_lot_shares
        parts = ((LotKind.BOARD_LOT, quantity - odd_shares), (LotKind.ODD_LOT, odd_shares))

        return [(kind, shares) for kind, shares in parts if shares]


@dataclass(frozen=True)
class FillRule:
    """
    What one fill of an order settles: the fee and tax of its shares at its price on the fill's date (TradingCostRule)
    and, for a SELL of shares the account holds, the realized PnL against their cost basis (Position.profit_on_sale).
    """

    cost_rule: TradingCostRule

    def apply(
        self, order: Order, quantity: int, price: float, held: Position | None, *, now: datetime
    ) -> tuple[TradeCost, float | None]:
        cost = self.cost_rule.apply(order.action, order.stock_id, price, quantity, now=now)

        if order.action == TradeAction.SELL and held is not None:
            return cost, held.profit_on_sale(quantity, cost.net)

        return cost, None


@dataclass(frozen=True)
class BrokerOutcomeRule:
    """
    The final status of an order a real broker took as one exchange order per lot part, once the parts it sent have
    reported. A FILLED order stays FILLED. Otherwise:
    - A part still working after a cancel request FAILS the order: the broker may still fill it, so `broker` is
      named as the place to check.
    - A part the broker ended as FAILED, or whose deals cannot be the whole story, FAILS the order instead of guessing
      what executed.
    - Nothing filled and every part refused: REJECTED as BROKER_REFUSED.
    - Anything else is CANCELLED with what filled: an IOC remainder, a FOK kill, or a refused part.
    """

    broker: str

    def apply(self, order: Order, reports: Sequence[BrokerOrderReport], now: datetime) -> None:
        if order.status == OrderStatus.FILLED:
            return

        summary = "; ".join(report.description for report in reports)

        if not all(report.is_done for report in reports):
            order.fail(f"still working at the broker after a cancel request, check {self.broker}: {summary}", now=now)
            return

        if any(report.status == OrderStatus.FAILED or report.deals_missing for report in reports):
            order.fail(f"unexplained broker result: {summary}", now=now)
            return

        if order.filled_quantity == 0 and all(report.status == OrderStatus.REJECTED for report in reports):
            order.reject(RejectReason.BROKER_REFUSED, summary, now=now)
            return

        order.cancel(f"{order.time_in_force.name} unfilled: filled {order.filled_quantity} of {order.quantity}; {summary}", now=now)
