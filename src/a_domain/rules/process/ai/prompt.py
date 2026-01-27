from src.a_domain.model.market.article import Article
from src.a_domain.types.enums import CandidateSource


class SentimentPromptBuilder:
    """
    Rule: Construct the prompt for AI Sentiment Analysis.
    Templates are injected via constructor to allow configuration from YAML.
    """

    _MAX_ARTICLES_TO_PROCESS = 10
    _MAX_CONTENT_PREVIEW_LENGTH = 500

    def __init__(self, fundamental_template: str, momentum_template: str):
        """
        Args:
            fundamental_template: Prompt for technical/fundamental stocks (Focus on Growth/EPS).
            momentum_template: Prompt for buzz/trending stocks (Focus on Hype/Risk).
        """
        self._fundamental_template = fundamental_template
        self._momentum_template = momentum_template

    def build(self, stock_id: str, source: CandidateSource, articles: list[Article]) -> str:
        selected_articles = articles[: self._MAX_ARTICLES_TO_PROCESS]

        formatted_entries: list[str] = []
        for index, article in enumerate(selected_articles, start=1):
            content_preview = (
                article.content[: self._MAX_CONTENT_PREVIEW_LENGTH]
                if len(article.content) > self._MAX_CONTENT_PREVIEW_LENGTH
                else article.content
            )
            # Minimal formatting to keep token usage efficient
            formatted_entries.append(f"[{index}] Title: {article.title}\nContent: {content_preview}")

        joined_articles_text = "\n\n".join(formatted_entries)

        # Select template based on source
        if source == CandidateSource.SOCIAL_BUZZ:
            return self._momentum_template.format(stock_id=stock_id, articles_text=joined_articles_text)

        # Default to Fundamental/Technical template
        return self._fundamental_template.format(stock_id=stock_id, articles_text=joined_articles_text)
