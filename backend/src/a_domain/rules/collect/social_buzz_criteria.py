from collections import defaultdict
from dataclasses import dataclass

import icontract

from a_domain.model.market.article import Article


@icontract.invariant(lambda self: self.min_mentions >= 0)
@icontract.invariant(lambda self: self.min_engagement >= 0)
@dataclass(frozen=True)
class SocialBuzzCriteria:
    """
    Decides which stocks are trending on social media: a stock trends when its posts reach `min_mentions`, or when
    their engagement adds up to `min_engagement`.
    """

    min_mentions: int
    min_engagement: int

    def apply(self, articles: list[Article]) -> dict[str, list[Article]]:
        """The posts of each trending stock by stock id, in the order the stocks were first mentioned."""
        articles_by_stock: dict[str, list[Article]] = defaultdict(list)

        for article in articles:
            articles_by_stock[article.stock_id].append(article)

        return {
            stock_id: stock_articles
            for stock_id, stock_articles in articles_by_stock.items()
            if len(stock_articles) >= self.min_mentions or sum(article.engagement for article in stock_articles) >= self.min_engagement
        }
