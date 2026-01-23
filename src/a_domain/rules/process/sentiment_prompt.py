from src.a_domain.model.market.article import Article


class SentimentPromptBuilder:
    """
    Rule: Construct the prompt for AI Sentiment Analysis.
    Pure domain logic: Transforms Articles into a formatted string for the LLM.
    """

    _PROMPT_TEMPLATE = """Analyse the following articles about stock {stock_id} and provide:
1. A confidence score (0-100) indicating bullish sentiment
2. Key bullish factors found in the articles
3. Key bearish factors found in the articles

Articles:
{articles_text}

Respond in this exact JSON format:
{{
    "confidence_score": <int 0-100>,
    "bullish_factors": "<comma-separated list>",
    "bearish_factors": "<comma-separated list>"
}}
"""

    _MAX_ARTICLES_TO_PROCESS = 10
    _MAX_CONTENT_PREVIEW_LENGTH = 500

    def build(self, stock_id: str, articles: list[Article]) -> str:
        selected_articles = articles[: self._MAX_ARTICLES_TO_PROCESS]

        formatted_entries: list[str] = []
        for index, article in enumerate(selected_articles, start=1):
            content_preview = (
                article.content[: self._MAX_CONTENT_PREVIEW_LENGTH]
                if len(article.content) > self._MAX_CONTENT_PREVIEW_LENGTH
                else article.content
            )
            formatted_entries.append(f"[{index}] Title: {article.title}\nContent: {content_preview}")

        joined_articles_text = "\n\n".join(formatted_entries)

        return self._PROMPT_TEMPLATE.format(stock_id=stock_id, articles_text=joined_articles_text)
