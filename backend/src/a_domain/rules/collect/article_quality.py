from pydantic import NonNegativeInt
from pydantic.dataclasses import dataclass

from a_domain.model.market.article import Article
from a_domain.types.enums import InformationSource


@dataclass(frozen=True)
class ArticleQualityRule:
    """
    Decides whether an article is worth the AI's reading: no spam keyword in its title or content, and at least the
    minimum length for its source. A gossip-board post must also name a financial keyword.
    """

    spam_keywords: frozenset[str]
    financial_keywords: frozenset[str]
    min_chars_stock: NonNegativeInt
    min_chars_news: NonNegativeInt
    min_chars_gossip: NonNegativeInt

    def apply(self, article: Article) -> bool:
        text = f"{article.title}\n{article.content}"

        if any(keyword in text for keyword in self.spam_keywords):
            return False

        match article.source:
            case InformationSource.PTT_STOCK:
                return len(article.content) >= self.min_chars_stock

            case InformationSource.NEWS_MEDIA:
                return len(article.content) >= self.min_chars_news

            case InformationSource.PTT_GOSSIPING:
                has_financial_keyword = any(keyword in article.content for keyword in self.financial_keywords)
                return len(article.content) >= self.min_chars_gossip and has_financial_keyword

            case _:
                return True
