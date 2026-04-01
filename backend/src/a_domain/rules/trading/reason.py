from a_domain.model.market.stock import Stock


class ReasonRule:
    """Builds a human-readable reason string for the trade signal."""

    # TODO: Might needa improve it later.
    def build(self, stock: Stock) -> str:
        parts: list[str] = []
        if stock.is_eliminated:
            parts.append(f"Tech: FAIL[{', '.join(stock.hard_failures)}]")
        else:
            parts.append("Tech: PASS")
            if stock.soft_failures:
                parts.append(f"Soft:[{', '.join(stock.soft_failures[:3])}]")

        if stock.analysis_report and stock.analysis_report.bullish_factors:
            parts.append(f"Bull: {stock.analysis_report.bullish_factors[:3]}")

        tech_str = str(stock.technical_score) if stock.technical_score is not None else "N/A"
        ai_str = str(stock.ai_score) if stock.ai_score is not None else "N/A"

        veto_flag = " [AI VETOED]" if (stock.combined_score == 69 and (stock.ai_score or 50) < 50) else ""

        parts.append(f"Score: {stock.combined_score}{veto_flag} (Tech: {tech_str} | AI: {ai_str})")

        return " | ".join(parts)
