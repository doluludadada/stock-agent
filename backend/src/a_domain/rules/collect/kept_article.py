from dataclasses import replace

from pydantic import NonNegativeInt
from pydantic.dataclasses import dataclass

from a_domain.model.market.article import Article


@dataclass(frozen=True, kw_only=True)
class KeptArticleRule:
    """
    An article as the article store keeps it: with the text its source's terms and the site's audience let the site
    hold, cut at `text_length`. The exchanges' open data is kept with its text on every site. A news site's article is
    kept with its text only where the site may read the news sites for its own analysis (`news_text`,
    Audience.news_articles), and by its title and address elsewhere; a board's post is always kept by title and address.
    A world feed's item is kept with the summary the feed itself gives of it, on every site that reads the feed.
    The text a site holds of a news site's article finds the article by meaning and is never shown or sent on: the
    stock page and the brief's prompt read Article.open_text.
    """

    news_text: bool
    text_length: NonNegativeInt

    def apply(self, article: Article) -> Article:
        if article.source.is_open_data or article.source.is_world:
            return replace(article, content=article.content[: self.text_length])

        if self.news_text and not article.source.is_social:
            return replace(article, content=article.content[: self.text_length])

        return replace(article, content="")
