from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime

from icontract import ensure, invariant, require

from a_domain.model.market.stock import Stock
from a_domain.model.trading.position import Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.reason import ExitReasonRule
from a_domain.types.enums import SignalSource, SkipReason, TradeAction


@dataclass(frozen=True)
class BlockedStockRule:
    """
    Why this run may not act on a stock any more, or None: the run's stop-loss check already sold it, or its realtime
    quote was missing or too old when fetched (RealtimeQuoteFeed marked it stale).
    """

    def apply(self, stock: Stock, risk_blocked_stock_ids: AbstractSet[str], stale_stock_ids: AbstractSet[str]) -> SkipReason | None:
        if stock.stock_id in risk_blocked_stock_ids:
            return SkipReason.RISK_BLOCKED

        if stock.stock_id in stale_stock_ids:
            return SkipReason.STALE_QUOTE

        return None


@dataclass(frozen=True)
class StopLossQuoteRule:
    """
    Why a held stock gets no stop-loss check now, or None: BlockedStockRule blocks it, or it has no realtime quote. A
    daily close never prices a stop-loss SELL.
    """

    blocked_rule: BlockedStockRule

    def apply(self, stock: Stock, risk_blocked_stock_ids: AbstractSet[str], stale_stock_ids: AbstractSet[str]) -> SkipReason | None:
        blocked = self.blocked_rule.apply(stock, risk_blocked_stock_ids, stale_stock_ids)

        if blocked is not None:
            return blocked

        if stock.realtime_bar is None:
            return SkipReason.NO_REALTIME_BAR

        return None


@invariant(lambda self: 0 < self.stop_loss_pct < 1)
@dataclass(frozen=True)
class StopLossRule:
    """
    The emergency SELL of a whole held position whose current price is at or below its stop-loss price, which sits
    `stop_loss_pct` below the position's average cost, buy fees included; None when the stop-loss is not hit.
    AccountRiskCheck runs it on its own, before any analysis; ExitRule runs it first.
    """

    stop_loss_pct: float
    reason_rule: ExitReasonRule

    @require(lambda stock: stock.current_price is not None, "Exit decision requires a valid current price")
    @require(lambda position: position.quantity > 0, "Exit decision requires a positive position quantity")
    @ensure(lambda result: result is None or (result.action == TradeAction.SELL and result.quantity > 0))
    def apply(self, stock: Stock, position: Position, *, now: datetime) -> TradeSignal | None:
        current_price = stock.current_price

        if current_price is None:
            raise ValueError("Stop-loss decision requires a valid current price")

        stop_loss_price = position.average_cost * (1 - self.stop_loss_pct)

        if current_price > stop_loss_price:
            return None

        return TradeSignal.of(
            stock,
            action=TradeAction.SELL,
            source=SignalSource.STOP_LOSS,
            score=stock.technical_score or 0,
            reason=self.reason_rule.apply(stock, position, TradeAction.SELL, "STOP_LOSS"),
            quantity=position.quantity,
            stop_loss_price=stop_loss_price,
            now=now,
        )


@invariant(lambda self: 0 <= self.sell_threshold <= 100)
@dataclass(frozen=True)
class ExitRule:
    """Sell-side rule for a held position: the stop-loss SELL first, then a SELL at or below `sell_threshold`, else HOLD."""

    sell_threshold: int
    stop_loss_rule: StopLossRule
    reason_rule: ExitReasonRule

    @require(lambda stock: stock.current_price is not None, "Exit decision requires a valid current price")
    @require(lambda position: position.quantity > 0, "Exit decision requires a positive position quantity")
    @ensure(lambda result: result.action != TradeAction.SELL or result.quantity > 0, "SELL signal must have positive quantity")
    def apply(self, stock: Stock, position: Position, *, now: datetime) -> TradeSignal:
        stop_loss_signal = self.stop_loss_rule.apply(stock, position, now=now)

        if stop_loss_signal is not None:
            return stop_loss_signal

        composite_score = stock.composite_score

        if composite_score is None:
            raise ValueError("Exit decision requires a composite score")

        should_sell = composite_score <= self.sell_threshold
        action = TradeAction.SELL if should_sell else TradeAction.HOLD
        cause = "SCORE_EXIT" if should_sell else "No sell condition met"

        return TradeSignal.of(
            stock,
            action=action,
            source=SignalSource.COMBINED,
            score=composite_score,
            reason=self.reason_rule.apply(stock, position, action, cause),
            quantity=position.quantity if should_sell else 0,
            now=now,
        )
