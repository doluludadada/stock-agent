from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.trading.position import Position


@dataclass(frozen=True)
class ReasonRule:
    """Builds readable reasons for entry and exit signals."""

    def build_entry(self, stock: Stock) -> str:
        parts: list[str] = ["Entry"]

        parts.append(self._technical_summary(stock))

        if stock.analysis_report and stock.analysis_report.bullish_factors:
            parts.append(f"Bull: {stock.analysis_report.bullish_factors[:3]}")

        parts.append(self._score_summary(stock))

        return " | ".join(parts)

    def build_exit(self, stock: Stock, position: Position, cause: str) -> str:
        parts: list[str] = [f"Exit: {cause}"]

        parts.append(f"Position: qty={position.quantity}, avg={position.average_cost:.2f}")

        if stock.current_price is not None:
            pnl = (stock.current_price - position.average_cost) * position.quantity
            parts.append(f"PnL: {pnl:.2f}")

        parts.append(self._technical_summary(stock))

        if stock.analysis_report and stock.analysis_report.bearish_factors:
            parts.append(f"Bear: {stock.analysis_report.bearish_factors[:3]}")

        parts.append(self._score_summary(stock))

        return " | ".join(parts)

    def build(self, stock: Stock) -> str:
        """
        Backward-compatible method.

        Existing code may still call ReasonRule.build(stock).
        Treat it as entry reason.
        """
        return self.build_entry(stock)

    def _technical_summary(self, stock: Stock) -> str:
        if stock.is_eliminated:
            return f"Tech: FAIL[{', '.join(stock.hard_failures)}]"

        if stock.soft_failures:
            return f"Tech: PASS | Soft:[{', '.join(stock.soft_failures[:3])}]"

        return "Tech: PASS"

    def _score_summary(self, stock: Stock) -> str:
        tech_str = str(stock.technical_score) if stock.technical_score is not None else "N/A"
        ai_str = str(stock.ai_score) if stock.ai_score is not None else "N/A"

        veto_flag = " [AI VETOED]" if stock.combined_score == 69 and (stock.ai_score or 50) < 50 else ""

        return f"Score: {stock.combined_score}{veto_flag} (Tech: {tech_str} | AI: {ai_str})"
