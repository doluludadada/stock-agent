from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.types.enums import CandidateSource


# TODO: It was clean
@dataclass(frozen=True)
class AiReportPromptBuilder:
    """
    Builds AI analysis prompts from stock context.

    This is pure string construction. It does not call an AI provider.
    """

    fundamental_template: str
    momentum_template: str
    max_articles: int
    max_content_length: int

    def build(self, stock: Stock) -> str:
        articles_text = self._build_articles_text(stock)

        if stock.historical_context:
            articles_text += f"\n\n[Past Analysis]\n{stock.historical_context}"

        if stock.source == CandidateSource.SOCIAL_BUZZ:
            return self.momentum_template.format(
                stock_id=stock.stock_id,
                articles_text=articles_text,
            )

        return self.fundamental_template.format(
            stock_id=stock.stock_id,
            articles_text=articles_text,
        )

    def _build_articles_text(self, stock: Stock) -> str:
        selected_articles = stock.articles[: self.max_articles]

        entries: list[str] = []

        for index, article in enumerate(selected_articles, 1):
            preview = article.content[: self.max_content_length]
            entries.append(f"[{index}] Title: {article.title}\nContent: {preview}")

        return "\n\n".join(entries)
