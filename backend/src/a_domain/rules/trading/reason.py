from backend.src.a_domain.model.market.stock import Stock


class ReasonRule:
    """Builds a human-readable reason string for the trade signal."""

    def build(self, stock: Stock) -> str:
        parts: list[str] = []

        if stock.is_eliminated:
            failed_str = ", ".join(stock.hard_failures)
            parts.append(f"Tech: FAIL[{failed_str}]")
        else:
            parts.append("Tech: PASS")
            if stock.soft_failures:
                soft_str = ", ".join(stock.soft_failures[:3])
                parts.append(f"Soft: [{soft_str}]")

        if stock.sentiment_report:
            if stock.sentiment_report.bullish_factors:
                parts.append(f"Bull: {stock.sentiment_report.bullish_factors[:3]}")

        parts.append(f"Score: {stock.combined_score}")

        return " | ".join(parts)
