from src.a_domain.model.market.article import Article
from src.a_domain.ports.analysis.quality_filter_port import QualityFilterPort
from src.a_domain.types.constants import FINANCIAL_KEYWORDS_TW
from src.a_domain.types.enums import InformationSource


class ArticleQualityFilter(QualityFilterPort):
    """
    Rule: Filters low-quality articles from PTT Stock board.

    High-quality articles must:
    1. Meet minimum character length requirement
    2. Contain at least 2 distinct financial keywords
    """

    def __init__(
        self,
        minimum_character_length: int = 300,
        required_keywords: frozenset[str] = FINANCIAL_KEYWORDS_TW,
    ):
        self._minimum_character_length = minimum_character_length
        self._required_keywords = required_keywords

    def is_high_quality(self, article: Article) -> bool:
        if article.source != InformationSource.PTT_STOCK:
            return True

        if len(article.content) < self._minimum_character_length:
            return False

        keyword_hit_count = sum(1 for keyword in self._required_keywords if keyword in article.content)
        return keyword_hit_count >= 2
