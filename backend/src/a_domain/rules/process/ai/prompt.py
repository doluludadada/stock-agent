from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.types.enums import CandidateSource


@dataclass(frozen=True)
class AiReportPromptBuilder:
    """
    Config-driven AI report prompt builder.
    Fields injected by b_application from AppConfig.
    """

    fundamental_template: str
    momentum_template: str
    max_articles: int
    max_content_length: int

    def build(self, stock: Stock) -> str:
        selected = stock.articles[: self.max_articles]
        entries = []
        for i, article in enumerate(selected, 1):
            preview = article.content[: self.max_content_length]
            entries.append(f"[{i}] Title: {article.title}\nContent: {preview}")
        joined = "\n\n".join(entries)

        if stock.historical_context:
            joined += f"\n\n[Past Analysis]\n{stock.historical_context}"

        if stock.source == CandidateSource.SOCIAL_BUZZ:
            return self.momentum_template.format(stock_id=stock.stock_id, articles_text=joined)
        return self.fundamental_template.format(stock_id=stock.stock_id, articles_text=joined)
