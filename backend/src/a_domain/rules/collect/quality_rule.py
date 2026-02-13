from dataclasses import dataclass

from backend.src.a_domain.model.market.article import Article
from backend.src.a_domain.types.enums import InformationSource


@dataclass
class QualityRule:
    """
    Rule: Determines if an article is worth processing.
    Values are injected from Config, not hardcoded.
    """

    spam_keywords: frozenset[str]
    financial_keywords: frozenset[str]

    min_chars_stock: int = 100
    min_chars_news: int = 200
    min_chars_gossip: int = 50

    def is_high_quality(self, article: Article) -> bool:
        return self.is_relevant(article)

    def is_relevant(self, article: Article) -> bool:
        if self._contains_spam(article):
            return False

        match article.source:
            case InformationSource.PTT_STOCK:
                return self._check_ptt_stock(article)

            case InformationSource.NEWS_MEDIA:
                return self._check_news(article)

            case InformationSource.PTT_GOSSIPING:
                return self._check_ptt_gossiping(article)

            case _:
                return True

    def _contains_spam(self, article: Article) -> bool:
        if any(k in article.title for k in self.spam_keywords):
            return True
        if any(k in article.content for k in self.spam_keywords):
            return True
        return False

    def _check_ptt_stock(self, article: Article) -> bool:
        return len(article.content) >= self.min_chars_stock

    def _check_news(self, article: Article) -> bool:
        return len(article.content) >= self.min_chars_news

    def _check_ptt_gossiping(self, article: Article) -> bool:
        if len(article.content) < self.min_chars_gossip:
            return False

        hit = any(k in article.content for k in self.financial_keywords)
        return hit


