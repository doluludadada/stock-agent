from dataclasses import dataclass

from a_domain.model.market.article import Article
from a_domain.types.enums import InformationSource


@dataclass
class QualityRule:
    """Determines if an article is worth processing. Values injected from Config."""

    spam_keywords: frozenset[str]
    financial_keywords: frozenset[str]

    min_chars_stock: int
    min_chars_news: int
    min_chars_gossip: int

    def is_high_quality(self, article: Article) -> bool:
        return self.is_relevant(article)

    def is_relevant(self, article: Article) -> bool:
        if self._contains_spam(article):
            return False
        match article.source:
            case InformationSource.PTT_STOCK:
                return len(article.content) >= self.min_chars_stock
            case InformationSource.NEWS_MEDIA:
                return len(article.content) >= self.min_chars_news
            case InformationSource.PTT_GOSSIPING:
                return self._check_ptt_gossiping(article)
            case _:
                return True

    def _contains_spam(self, article: Article) -> bool:
        return any(k in article.title or k in article.content for k in self.spam_keywords)

    def _check_ptt_gossiping(self, article: Article) -> bool:
        if len(article.content) < self.min_chars_gossip:
            return False
        return any(k in article.content for k in self.financial_keywords)
