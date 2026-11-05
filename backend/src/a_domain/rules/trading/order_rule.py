from datetime import datetime

from pydantic.dataclasses import dataclass

from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.collect.freshness import DataFreshnessRule
from a_domain.rules.trading.tick import LimitPriceRule
from a_domain.types.enums import ExecutionProvider, OrderMode, OrderType, RejectReason, TimeInForce, TradeAction, TradingPhase
from a_domain.types.ids import RunId


@dataclass(frozen=True)
class OrderGateRule:
    """
    Why the app may not send an order for this decision now, or None. The gates run per decision right before
    submission, against one reading of the clock: the order mode and execution provider, continuous trading (the
    opening and closing call auctions take ROD only, and the app sends IOC), and the price age. The age is measured
    from the quote behind the decision to `now`, so a quote that was fresh when fetched but aged while the run
    analysed other stocks is refused.
    """

    order_mode: OrderMode
    execution_provider: ExecutionProvider
    price_freshness: DataFreshnessRule

    def apply(self, signal: TradeSignal, now: datetime, phase: TradingPhase) -> tuple[RejectReason, str] | None:
        if self.order_mode == OrderMode.DISABLED:
            return RejectReason.ORDER_MODE_DISABLED, "trading.order_mode is disabled"

        if self.order_mode == OrderMode.MOCK_ONLY and self.execution_provider != ExecutionProvider.MOCK:
            return RejectReason.ORDER_MODE_MISMATCH, f"mock_only order mode cannot use {self.execution_provider.value}"

        if self.order_mode == OrderMode.LIVE and self.execution_provider == ExecutionProvider.MOCK:
            return RejectReason.ORDER_MODE_MISMATCH, "live order mode cannot use the mock execution provider"

        if phase != TradingPhase.CONTINUOUS:
            detail = f"{now:%a %Y-%m-%d %H:%M} falls in the market's {phase} phase; IOC orders trade only in continuous trading"
            return RejectReason.MARKET_CLOSED, detail

        if self.price_freshness.apply(signal.price_observed_at, now):
            return None

        age_minutes = int((now - signal.price_observed_at).total_seconds() // 60)
        limit_minutes = int(self.price_freshness.max_lag.total_seconds() // 60)
        detail = (
            f"price {signal.price_at_signal:.2f} was quoted at {signal.price_observed_at:%Y-%m-%d %H:%M}, "
            f"{age_minutes} min before {now:%H:%M}; the limit is {limit_minutes} min"
        )
        return RejectReason.STALE_PRICE, detail


@dataclass(frozen=True)
class OrderRule:
    """
    Turns a BUY or SELL decision into the order the app may send now, or into a REJECTED order that says why not
    (OrderGateRule).

    Every order is a LIMIT at the decision's price with time in force IOC:
    - LIMIT at the price the decision saw, as an exchange tick (LimitPriceRule). A traded price is a tick, so no fill
      is worse than what was decided on. A price off the tick grid rounds up for a BUY and down for a SELL, at most
      one tick, so the order still executes at that price.
    - IOC trades what is available at that price now and cancels the rest at once. The app tracks no
      working orders (no cancel, no expiry, no reconciliation), so ROD is out: its remainder could fill
      hours later at a price no decision saw. FOK is out because sizing gives a maximum, not a target:
      a partial BUY is still a valid smaller position and a partial stop-loss SELL still cuts the loss.
    - IOC trades only in continuous trading, so an order outside it is REJECTED as MARKET_CLOSED and never sent.
    """

    gate_rule: OrderGateRule
    limit_price_rule: LimitPriceRule

    def apply(self, signal: TradeSignal, run_id: RunId, now: datetime, phase: TradingPhase) -> Order:
        action = signal.action

        if action == TradeAction.HOLD:
            raise ValueError("HOLD is not an order")

        order = Order(
            run_id=run_id,
            decision_id=signal.decision_id,
            stock_id=signal.stock_id,
            action=action,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.IOC,
            quantity=signal.quantity,
            limit_price=self.limit_price_rule.apply(action, signal.stock_id, signal.price_at_signal),
            created_at=now,
            updated_at=now,
        )
        refusal = self.gate_rule.apply(signal, now, phase)

        if refusal is not None:
            order.reject(*refusal, now=now)

        return order
