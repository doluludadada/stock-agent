from backend.src.a_domain.model.analysis.stock_candidate import StockCandidate
from backend.src.a_domain.types.enums import CandidateSource


class SentimentPromptBuilder:
    # TODO: Shouldn't in here.
    _MAX_ARTICLES = 10
    _MAX_CONTENT_LENGTH = 500

    def __init__(self, fundamental_template: str, momentum_template: str):
        self._fundamental_template = fundamental_template
        self._momentum_template = momentum_template

    def build(self, candidate: StockCandidate) -> str:
        selected = candidate.articles[: self._MAX_ARTICLES]
        entries = []
        for i, article in enumerate(selected, 1):
            preview = article.content[: self._MAX_CONTENT_LENGTH]
            entries.append(f"[{i}] Title: {article.title}\nContent: {preview}")
        joined = "\n\n".join(entries)

        if candidate.historical_context:
            joined += f"\n\n[Past Analysis]\n{candidate.historical_context}"

        if candidate.source == CandidateSource.SOCIAL_BUZZ:
            return self._momentum_template.format(stock_id=candidate.stock.stock_id, articles_text=joined)
        return self._fundamental_template.format(stock_id=candidate.stock.stock_id, articles_text=joined)
