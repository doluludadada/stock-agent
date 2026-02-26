from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.types.enums import CandidateSource


class SentimentPromptBuilder:
    # TODO: Shouldn't in here.
    _MAX_ARTICLES = 10
    _MAX_CONTENT_LENGTH = 500

    def __init__(self, fundamental_template: str, momentum_template: str):
        self._fundamental_template = fundamental_template
        self._momentum_template = momentum_template

    def build(self, stock: Stock) -> str:
        selected = stock.articles[: self._MAX_ARTICLES]
        entries = []
        for i, article in enumerate(selected, 1):
            preview = article.content[: self._MAX_CONTENT_LENGTH]
            entries.append(f"[{i}] Title: {article.title}\nContent: {preview}")
        joined = "\n\n".join(entries)

        if stock.historical_context:
            joined += f"\n\n[Past Analysis]\n{stock.historical_context}"

        if stock.source == CandidateSource.SOCIAL_BUZZ:
            return self._momentum_template.format(stock_id=stock.stock_id, articles_text=joined)
        return self._fundamental_template.format(stock_id=stock.stock_id, articles_text=joined)
