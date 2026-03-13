from datetime import datetime, timezone
from uuid import uuid4

import httpx

from a_domain.model.market.article import Article
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import ContentType, InformationSource


# TODO:
class CnyesNewsProvider:
    """
    Fetches news from Cnyes (鉅亨網) using their internal JSON API.
    This is much more stable than HTML scraping.
    """

    def __init__(self, logger: ILoggingProvider):
        self._logger = logger
        self._api_url = "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock"

    async def fetch_news(self, stock_id: str, limit: int = 5) -> list[Article]:
        self._logger.debug(f"Fetching Cnyes News for {stock_id} via API...")

        params = {"q": stock_id, "limit": limit}

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(self._api_url, params=params)
                resp.raise_for_status()

                # Cnyes returns pure JSON
                data = resp.json()
                items = data.get("items", {}).get("data", [])

                articles: list[Article] = []

                for item in items:
                    # Cnyes gives Unix timestamp (seconds)
                    # TODO: Why there's so many hard code is it from json?
                    publish_at_ts = item.get("publishAt")
                    if publish_at_ts:
                        pub_date = datetime.fromtimestamp(publish_at_ts, tz=timezone.utc)
                    else:
                        pub_date = datetime.now(timezone.utc)

                    news_id = item.get("newsId", "")

                    article = Article(
                        id=uuid4(),
                        stock_id=stock_id,
                        source=InformationSource.NEWS_MEDIA,
                        title=item.get("title", "").strip(),
                        content=item.get("summary", "").strip(),
                        url=f"https://news.cnyes.com/news/id/{news_id}",
                        content_type=ContentType.REPORT,
                        published_at=pub_date,
                        fetched_at=datetime.now(timezone.utc),
                        raw_metadata={"newsId": news_id, "keyword": item.get("keyword")},
                    )
                    articles.append(article)

                self._logger.info(f"Successfully fetched {len(articles)} Cnyes articles for {stock_id}.")
                return articles

            except httpx.RequestError as e:
                self._logger.error(f"HTTP Error fetching Cnyes API for {stock_id}: {e}")
                return []
            except Exception as e:
                self._logger.error(f"Unexpected error parsing Cnyes API for {stock_id}: {e}")
                return []
