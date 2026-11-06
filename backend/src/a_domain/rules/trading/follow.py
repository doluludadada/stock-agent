from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from pydantic.dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account, Position
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.types.enums import FollowRefusal, OrderPricing, SignalSource, TradeAction, TradingPhase


@dataclass(frozen=True)
class OpenDecisionsRule:
    """
    The decisions of `run` a follow may still take: its BUYs, and its SELLs of a stock the account holds now, when the
    run is a finished run of a followable workflow, but each one a follow order of which filled, in full or in part,
    since the mock account opened, and only the first of a stock's, so a follow places at most one order per stock. A
    refused or unsent follow, or one before the account's last reset, leaves the decision open.
    """

    def apply(
        self, run: SystemStats, decisions: Sequence[TradeSignal], follows: Sequence[tuple[TradeSignal, Order]], account: Account
    ) -> list[TradeSignal]:
        if not run.workflow.followable or run.end_time is None or run.failure is not None:
            return []

        followed = {
            follow.followed_decision_id
            for follow, order in follows
            if order.filled_quantity > 0 and (account.opened_at is None or order.created_at >= account.opened_at)
        }
        open_decisions: dict[str, TradeSignal] = {}

        for decision in decisions:
            held = decision.stock_id in account.stock_ids
            orderable = decision.action == TradeAction.BUY or (decision.action == TradeAction.SELL and held)

            if orderable and decision.decision_id not in followed:
                open_decisions.setdefault(decision.stock_id, decision)

        return list(open_decisions.values())


@dataclass(frozen=True)
class FollowWindowRule:
    """Why the open decisions cannot be followed in the market's phase now, or None when a follow may start."""

    pricing: OrderPricing

    def apply(self, open_decisions: Sequence[TradeSignal], phase: TradingPhase) -> FollowRefusal | None:
        if not open_decisions:
            return FollowRefusal.NOTHING_TO_FOLLOW

        if phase != self.pricing.trading_phase:
            return FollowRefusal.OUTSIDE_FOLLOW_WINDOW

        return None


@dataclass(frozen=True)
class FollowRule:
    """
    The follow decision of one open decision at `now`, or why it gets none now and stays open. It keeps the decision's
    stock, action, score, reason and stop, takes the stock's current price, and names the decision it follows. A BUY
    keeps its shares; a SELL sells at most the shares held now, and nothing when none are held. The order gates judge
    the price when the order is placed.
    """

    def apply(self, decision: TradeSignal, stock: Stock | None, held: Position | None, now: datetime) -> TradeSignal | str:
        if decision.action == TradeAction.SELL and held is None:
            return "not held now"

        if stock is None or stock.current_price is None:
            return "no price: the stock has neither a realtime quote nor an official close"

        quantity = min(decision.quantity, held.quantity) if decision.action == TradeAction.SELL and held else decision.quantity
        follow = TradeSignal.of(
            stock,
            now,
            decision.action,
            SignalSource.FOLLOW,
            decision.score,
            f"Follows the {decision.action} of {decision.generated_at:%Y-%m-%d %H:%M}: {decision.reason}",
            quantity,
            decision.stop_loss_price,
        )
        return replace(follow, followed_decision_id=decision.decision_id)
