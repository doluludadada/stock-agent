from backend.src.a_domain.model.analysis.stock_candidate import StockCandidate


class ReasonRule:
    """Builds a human-readable reason string for the trade signal."""

    def build(self, candidate: StockCandidate) -> str:
        parts: list[str] = []

        if candidate.is_eliminated:
            failed_str = ", ".join(candidate.hard_failures)
            parts.append(f"Tech: FAIL[{failed_str}]")
        else:
            parts.append("Tech: PASS")
            if candidate.soft_failures:
                soft_str = ", ".join(candidate.soft_failures[:3])
                parts.append(f"Soft: [{soft_str}]")

        if candidate.sentiment_report:
            if candidate.sentiment_report.bullish_factors:
                parts.append(f"Bull: {candidate.sentiment_report.bullish_factors[:3]}")

        parts.append(f"Score: {candidate.combined_score}")

        return " | ".join(parts)
