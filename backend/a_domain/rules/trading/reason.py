# src\a_domain\rules\trading\reason.py
from src.a_domain.model.analysis.analysis_context import AnalysisContext


class ReasonRule:
    """
    Rule: Builds a human-readable reason string for the trade signal.
    """

    def build(self, context: AnalysisContext) -> str:
        reason_parts: list[str] = []

        # Technical Status
        if context.is_passed:
            reason_parts.append("Tech: PASS")
        else:
            failed_str = ",".join(context.technical_failures)
            reason_parts.append(f"Tech: FAIL[{failed_str}]")

        # Sentiment Status
        if context.sentiment_report:
            if context.sentiment_report.bullish_factors:
                reason_parts.append(f"Bull: {context.sentiment_report.bullish_factors[:3]}")

        reason_parts.append(f"Score: {context.combined_score}")

        return " | ".join(reason_parts)
