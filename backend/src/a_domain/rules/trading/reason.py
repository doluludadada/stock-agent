# backend/src/a_domain/rules/trading/reason.py

from icontract import ensure

from a_domain.model.market.stock import Stock
from a_domain.model.trading.position import Position


class ReasonRule:
    """
    Builds readable reasons for entry, exit, and hold decisions.

    - TradeSignal.reason is the final human-readable explanation.
    - No separate SignalReason enum is needed for current workflow.
    - Stateless: all methods are @staticmethod. No instantiation needed.
    """

    @staticmethod
    @ensure(lambda result: len(result) > 0, "Reason must not be empty")
    def build_entry(stock: Stock) -> str:
        """
        Builds BUY reason for non-held stock.

        - Used when EntryRule produces an executable BUY signal.
        - EntryRule may prepend ADD_POSITION when the stock is already held.
        """
        parts = [
            "Entry: BUY",
            ReasonRule.build_technical_summary(stock),
        ]

        if stock.ai_report and stock.ai_report.bullish_factors:
            parts.append(f"Bull: {stock.ai_report.bullish_factors[:3]}")

        parts.append(ReasonRule.build_score_summary(stock))
        return " | ".join(parts)

    @staticmethod
    @ensure(lambda result: len(result) > 0, "Reason must not be empty")
    def build_entry_hold(stock: Stock, cause: str) -> str:
        """
        Builds HOLD reason for non-held stock.

        - HOLD is a real decision, not None.
        """
        parts = [
            f"Entry: HOLD - {cause}",
            ReasonRule.build_technical_summary(stock),
        ]

        if stock.ai_report and stock.ai_report.bearish_factors:
            parts.append(f"Risk: {stock.ai_report.bearish_factors[:3]}")

        parts.append(ReasonRule.build_score_summary(stock))
        return " | ".join(parts)

    @staticmethod
    @ensure(lambda result: len(result) > 0, "Reason must not be empty")
    def build_exit(stock: Stock, position: Position, cause: str) -> str:
        """
        Builds SELL reason for held position.

        - Used when ExitRule produces an executable SELL signal.
        """
        parts = [
            f"Exit: SELL - {cause}",
            f"Position: qty={position.quantity}, avg={position.average_cost:.2f}",
        ]

        if stock.current_price is not None:
            profit_loss = (stock.current_price - position.average_cost) * position.quantity
            parts.append(f"PnL: {profit_loss:.2f}")

        parts.append(ReasonRule.build_technical_summary(stock))

        if stock.ai_report and stock.ai_report.bearish_factors:
            parts.append(f"Bear: {stock.ai_report.bearish_factors[:3]}")

        parts.append(ReasonRule.build_score_summary(stock))
        return " | ".join(parts)

    @staticmethod
    @ensure(lambda result: len(result) > 0, "Reason must not be empty")
    def build_exit_hold(stock: Stock, position: Position, cause: str) -> str:
        """
        Builds HOLD reason for held position.

        - A held stock with no exit trigger should still produce
          an explicit HOLD decision.
        """
        parts = [
            f"Exit: HOLD - {cause}",
            f"Position: qty={position.quantity}, avg={position.average_cost:.2f}",
        ]

        if stock.current_price is not None:
            profit_loss = (stock.current_price - position.average_cost) * position.quantity
            parts.append(f"Unrealized PnL: {profit_loss:.2f}")

        parts.append(ReasonRule.build_technical_summary(stock))
        parts.append(ReasonRule.build_score_summary(stock))
        return " | ".join(parts)

    @staticmethod
    def build(stock: Stock) -> str:
        """
        Backward-compatible method.

        Existing code may still call ReasonRule.build(stock).
        Treat it as entry reason until old callers are removed.
        """
        return ReasonRule.build_entry(stock)

    @staticmethod
    def build_technical_summary(stock: Stock) -> str:
        """
        Summarizes technical result.

        Reason strings should expose hard/soft failures
        without leaking internal objects.
        """
        if stock.is_eliminated:
            return f"Tech: FAIL[{', '.join(stock.hard_failures)}]"

        if stock.soft_failures:
            return f"Tech: PASS | Soft:[{', '.join(stock.soft_failures[:3])}]"

        return "Tech: PASS"

    @staticmethod
    def build_score_summary(stock: Stock) -> str:
        """
        Summarizes final score components.

        BUY/SELL/HOLD decisions should be traceable to technical score,
        AI score, and composite score.
        """
        technical_score = str(stock.technical_score) if stock.technical_score is not None else "N/A"
        ai_score = str(stock.ai_score) if stock.ai_score is not None else "N/A"
        composite_score = str(stock.composite_score) if stock.composite_score is not None else "N/A"

        return f"Score: {composite_score} (Tech: {technical_score} | AI: {ai_score})"
