from dataclasses import dataclass

from icontract import ensure

from a_domain.model.market.stock import Stock
from a_domain.model.trading.position import Position
from a_domain.types.enums import TradeAction


@dataclass(frozen=True)
class AnalysisSummaryRule:
    """
    The analysis every decision reason ends with: the technical verdict, the AI factors the decision cites, and the
    scores, so a BUY, SELL or HOLD can be traced to its technical, AI and composite score. The verdict names the hard
    failures, or at most `item_limit` soft failures, without leaking internal objects.
    """

    item_limit: int

    def apply(self, stock: Stock, cited_factors: list[str]) -> str:
        technical = "Tech: PASS"

        if stock.soft_failures:
            technical = f"Tech: PASS | Soft:[{', '.join(stock.soft_failures[: self.item_limit])}]"

        if stock.is_eliminated:
            technical = f"Tech: FAIL[{', '.join(stock.hard_failures)}]"

        technical_score = str(stock.technical_score) if stock.technical_score is not None else "N/A"
        ai_score = str(stock.ai_score) if stock.ai_score is not None else "N/A"
        composite_score = str(stock.composite_score) if stock.composite_score is not None else "N/A"

        return " | ".join([technical, *cited_factors, f"Score: {composite_score} (Tech: {technical_score} | AI: {ai_score})"])


@dataclass(frozen=True)
class EntryReasonRule:
    """
    Why a stock that is not held is bought, or held off when `hold_cause` says why. A BUY cites at most `item_limit`
    bullish AI factors, a HOLD as many bearish ones. EntryRule prepends ADD_POSITION when the stock is already held.
    """

    item_limit: int
    summary_rule: AnalysisSummaryRule

    @ensure(lambda result: len(result) > 0, "Reason must not be empty")
    def apply(self, stock: Stock, hold_cause: str | None) -> str:
        report = stock.ai_report

        if hold_cause is None:
            cited = [f"Bull: {report.bullish_factors[: self.item_limit]}"] if report and report.bullish_factors else []
            return f"Entry: BUY | {self.summary_rule.apply(stock, cited)}"

        cited = [f"Risk: {report.bearish_factors[: self.item_limit]}"] if report and report.bearish_factors else []
        return f"Entry: HOLD - {hold_cause} | {self.summary_rule.apply(stock, cited)}"


@dataclass(frozen=True)
class ExitReasonRule:
    """
    Why a held position is sold or kept: the cause, the position and its profit or loss at the current price, and
    the analysis. A SELL cites at most `item_limit` bearish AI factors. A HOLD is a real decision with its own reason.
    """

    item_limit: int
    summary_rule: AnalysisSummaryRule

    @ensure(lambda result: len(result) > 0, "Reason must not be empty")
    def apply(self, stock: Stock, position: Position, action: TradeAction, cause: str) -> str:
        parts = [f"Exit: {action.name} - {cause}", f"Position: qty={position.quantity}, avg={position.average_cost:.2f}"]
        selling = action == TradeAction.SELL

        if stock.current_price is not None:
            profit_loss = (stock.current_price - position.average_cost) * position.quantity
            parts.append(f"{'PnL' if selling else 'Unrealized PnL'}: {profit_loss:.2f}")

        report = stock.ai_report
        cited = [f"Bear: {report.bearish_factors[: self.item_limit]}"] if selling and report and report.bearish_factors else []

        return " | ".join([*parts, self.summary_rule.apply(stock, cited)])
