from dataclasses import dataclass

from a_domain.model.market.article import Article
from a_domain.types.enums import InformationSource


@dataclass(frozen=True)
class ArticleQualityRule:
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
                return self._is_relevant_gossiping_article(article)

            case _:
                return True

    def _contains_spam(self, article: Article) -> bool:
        text = f"{article.title}\n{article.content}"

        return any(keyword in text for keyword in self.spam_keywords)

    def _is_relevant_gossiping_article(self, article: Article) -> bool:
        if len(article.content) < self.min_chars_gossip:
            return False

        if not self.financial_keywords:
            return False

        return any(keyword in article.content for keyword in self.financial_keywords)
