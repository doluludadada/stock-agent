from a_domain.model.market.stock import Stock


class ReasonRule:
    """Builds a human-readable reason string for the trade signal."""

    def build(self, stock: Stock) -> str:
        parts: list[str] = []
        if stock.is_eliminated:
            parts.append(f"Tech: FAIL[{', '.join(stock.hard_failures)}]")
        else:
            parts.append("Tech: PASS")
            if stock.soft_failures:
                parts.append(f"Soft: [{', '.join(stock.soft_failures[:3])}]")
        if stock.analysis_report and stock.analysis_report.bullish_factors:
            parts.append(f"Bull: {stock.analysis_report.bullish_factors[:3]}")
        parts.append(f"Score: {stock.combined_score}")
        return " | ".join(parts)
