# backend/src/a_domain/rules/trading/reason.py

from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.trading.position import Position


# NOTE: Might improve in the future
@dataclass(frozen=True)
class ReasonRule:
    """
    Builds readable reasons for entry, exit, and hold decisions.
        - TradeSignal.reason is the final human-readable explanation.
        - No separate SignalReason enum is needed for current workflow.
    """

    def build_entry(self, stock: Stock) -> str:
        """
        Builds BUY reason for non-held stock.
        - Used when EntryRule produces an executable BUY signal.
        """
        parts: list[str] = ["Entry: BUY"]

        parts.append(self._technical_summary(stock))

        if stock.analysis_report and stock.analysis_report.bullish_factors:
            parts.append(f"Bull: {stock.analysis_report.bullish_factors[:3]}")

        parts.append(self._score_summary(stock))

        return " | ".join(parts)

    def build_entry_hold(self, stock: Stock, cause: str) -> str:
        """
        Builds HOLD reason for non-held stock.
            - HOLD is a real decision, not None.
        """
        parts: list[str] = [f"Entry: HOLD - {cause}"]

        parts.append(self._technical_summary(stock))

        if stock.analysis_report and stock.analysis_report.bearish_factors:
            parts.append(f"Risk: {stock.analysis_report.bearish_factors[:3]}")

        parts.append(self._score_summary(stock))

        return " | ".join(parts)

    def build_exit(self, stock: Stock, position: Position, cause: str) -> str:
        """
        Builds SELL reason for held position.
            - Used when ExitRule produces an executable SELL signal.
        """
        parts: list[str] = [f"Exit: SELL - {cause}"]

        parts.append(f"Position: qty={position.quantity}, avg={position.average_cost:.2f}")

        if stock.current_price is not None:
            pnl = (stock.current_price - position.average_cost) * position.quantity
            parts.append(f"PnL: {pnl:.2f}")

        parts.append(self._technical_summary(stock))

        if stock.analysis_report and stock.analysis_report.bearish_factors:
            parts.append(f"Bear: {stock.analysis_report.bearish_factors[:3]}")

        parts.append(self._score_summary(stock))

        return " | ".join(parts)

    def build_exit_hold(self, stock: Stock, position: Position, cause: str) -> str:
        """
        Builds HOLD reason for held position.
            - A held stock with no exit trigger should still produce an explicit HOLD decision.
        """
        parts: list[str] = [f"Exit: HOLD - {cause}"]

        parts.append(f"Position: qty={position.quantity}, avg={position.average_cost:.2f}")

        if stock.current_price is not None:
            pnl = (stock.current_price - position.average_cost) * position.quantity
            parts.append(f"Unrealized PnL: {pnl:.2f}")

        parts.append(self._technical_summary(stock))
        parts.append(self._score_summary(stock))

        return " | ".join(parts)

    def build(self, stock: Stock) -> str:
        """
        Backward-compatible method.

        Existing code may still call ReasonRule.build(stock).
        Treat it as entry reason until old callers are removed.
        """
        return self.build_entry(stock)

    def _technical_summary(self, stock: Stock) -> str:
        """
        Summarizes technical result.

        Reason strings should expose hard/soft failures without leaking internal objects.
        """
        if stock.is_eliminated:
            return f"Tech: FAIL[{', '.join(stock.hard_failures)}]"

        if stock.soft_failures:
            return f"Tech: PASS | Soft:[{', '.join(stock.soft_failures[:3])}]"

        return "Tech: PASS"

    def _score_summary(self, stock: Stock) -> str:
        """
        Summarizes final score components.

        BUY/SELL/HOLD decisions should be traceable to technical score, AI score, and combined score.
        """
        tech_str = str(stock.technical_score) if stock.technical_score is not None else "N/A"
        ai_str = str(stock.ai_score) if stock.ai_score is not None else "N/A"

        veto_flag = " [AI VETOED]" if stock.combined_score == 69 and (stock.ai_score or 50) < 50 else ""

        return f"Score: {stock.combined_score}{veto_flag} (Tech: {tech_str} | AI: {ai_str})"
