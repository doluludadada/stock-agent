from datetime import UTC, datetime

import pytest

from a_domain.model.market.article import Article
from a_domain.rules.collect import ArticleQualityRule
from a_domain.types.enums import InformationSource

RULE = ArticleQualityRule(
    spam_keywords=frozenset({"業配"}),
    financial_keywords=frozenset({"營收"}),
    min_chars_stock=10,
    min_chars_news=20,
    min_chars_gossip=5,
)


def article(source: InformationSource, content: str, title: str = "title") -> Article:
    published_at = datetime(2026, 10, 30, tzinfo=UTC)
    return Article(stock_id="2330", source=source, title=title, content=content, published_at=published_at, fetched_at=published_at)


@pytest.mark.parametrize(
    ("source", "content", "accepted"),
    [
        (InformationSource.PTT_STOCK, "x" * 10, True),
        (InformationSource.PTT_STOCK, "x" * 9, False),
        (InformationSource.NEWS_MEDIA, "x" * 20, True),
        (InformationSource.NEWS_MEDIA, "x" * 19, False),
        (InformationSource.PTT_GOSSIPING, "本季營收創高", True),
        (InformationSource.PTT_GOSSIPING, "今天天氣很好呢", False),
        (InformationSource.PTT_GOSSIPING, "營收", False),
    ],
)
def test_an_article_needs_the_minimum_length_of_its_source(source: InformationSource, content: str, accepted: bool) -> None:
    assert RULE.apply(article(source, content)) is accepted


@pytest.mark.parametrize(("title", "content"), [("業配文", "x" * 50), ("title", "這是業配" + "x" * 50)])
def test_a_spam_keyword_in_the_title_or_content_rejects_any_article(title: str, content: str) -> None:
    assert RULE.apply(article(InformationSource.NEWS_MEDIA, content, title)) is False
