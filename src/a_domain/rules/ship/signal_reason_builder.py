from src.a_domain.model.analysis.analysis_context import AnalysisContext


class SignalReasonBuilder:
    """
    Rule: Builds a human-readable reason string for the trade signal.
    Pure domain logic with no private methods.
    """

    def build(self, context: AnalysisContext) -> str:
        reason_parts: list[str] = []

        if context.screening_result:
            if context.screening_result.passed:
                reason_parts.append("Tech: PASS")
            else:
                failed_rules = ",".join(context.screening_result.failed_rules)
                reason_parts.append(f"Tech: FAIL({failed_rules})")

        if context.sentiment_report:
            if context.sentiment_report.bullish_factors:
                reason_parts.append(f"Bull: {context.sentiment_report.bullish_factors}")
            if context.sentiment_report.bearish_factors:
                reason_parts.append(f"Bear: {context.sentiment_report.bearish_factors}")

        reason_parts.append(f"Score: {context.combined_score}")

        return " | ".join(reason_parts)
