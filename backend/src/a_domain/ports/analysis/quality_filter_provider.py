from typing import Protocol

from backend.src.a_domain.model.market.article import Article


class IQualityFilterProvider(Protocol):
    """
    Defines the standard for any rule that filters articles.
    """

    def is_high_quality(self, article: Article) -> bool: ...


