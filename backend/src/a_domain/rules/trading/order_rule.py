from dataclasses import dataclass
from datetime import datetime

from icontract import ensure, require

from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.collect.freshness import DataFreshnessRule
from a_domain.rules.trading.tick import TickRule
from a_domain.types.enums import (
    ExecutionProvider,
    OrderMode,
    OrderStatus,
    OrderType,
    RejectReason,
    TimeInForce,
    TradeAction,
    TradingPhase,
)
from a_domain.types.ids import RunId


@dataclass(frozen=True)
class OrderRule:
    """
    Turns a BUY or SELL decision into the order the app may send now, or into a REJECTED order that says why not.

    Every order is a LIMIT at the decision's price with time in force IOC:
    - LIMIT at the price the decision saw, as an exchange tick (TickRule). A traded price is a tick, so no fill is
      worse than what was decided on. A price off the tick grid rounds up for a BUY and down for a SELL, at most
      one tick, so the order still executes at that price.
    - IOC trades what is available at that price now and cancels the rest at once. The app tracks no
      working orders (no cancel, no expiry, no reconciliation), so ROD is out: its remainder could fill
      hours later at a price no decision saw. FOK is out because sizing gives a maximum, not a target:
      a partial BUY is still a valid smaller position and a partial stop-loss SELL still cuts the loss.
    - IOC trades only in continuous trading, so an order outside it (the opening and closing call auctions
      take ROD only) is REJECTED as MARKET_CLOSED and never sent.

    The gates run per decision right before submission, against one reading of the clock. The price
    age is measured from the quote behind the decision to `now`, so a quote that was fresh when fetched
    but aged while the run analysed other stocks is refused.
    """

    order_mode: OrderMode
    execution_provider: ExecutionProvider
    price_freshness: DataFreshnessRule

    @require(lambda signal: signal.action != TradeAction.HOLD, "HOLD is not an order")
    @ensure(lambda result: result.status in {OrderStatus.PENDING, OrderStatus.REJECTED})
    def order_for(self, signal: TradeSignal, run_id: RunId, now: datetime, phase: TradingPhase) -> Order:
        order = Order(
            run_id=run_id,
            decision_id=signal.decision_id,
            stock_id=signal.stock_id,
            action=signal.action,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.IOC,
            quantity=signal.quantity,
            limit_price=TickRule.limit_price(signal.action, signal.stock_id, signal.price_at_signal),
            created_at=now,
            updated_at=now,
        )

        if self.order_mode == OrderMode.DISABLED:
            order.reject(RejectReason.ORDER_MODE_DISABLED, "trading.order_mode is disabled", now=now)

        elif self.order_mode == OrderMode.MOCK_ONLY and self.execution_provider != ExecutionProvider.MOCK:
            order.reject(RejectReason.ORDER_MODE_MISMATCH, f"mock_only order mode cannot use {self.execution_provider.value}", now=now)

        elif self.order_mode == OrderMode.LIVE and self.execution_provider == ExecutionProvider.MOCK:
            order.reject(RejectReason.ORDER_MODE_MISMATCH, "live order mode cannot use the mock execution provider", now=now)

        elif phase != TradingPhase.CONTINUOUS:
            order.reject(
                RejectReason.MARKET_CLOSED,
                f"{now:%a %Y-%m-%d %H:%M} falls in the market's {phase} phase; IOC orders trade only in continuous trading",
                now=now,
            )

        elif not self.price_freshness.is_fresh(signal.price_observed_at, now):
            age_minutes = int(self.price_freshness.age(signal.price_observed_at, now).total_seconds() // 60)
            limit_minutes = int(self.price_freshness.max_lag.total_seconds() // 60)
            order.reject(
                RejectReason.STALE_PRICE,
                f"price {signal.price_at_signal:.2f} was quoted at {signal.price_observed_at:%Y-%m-%d %H:%M}, "
                f"{age_minutes} min before {now:%H:%M}; the limit is {limit_minutes} min",
                now=now,
            )

        return order
