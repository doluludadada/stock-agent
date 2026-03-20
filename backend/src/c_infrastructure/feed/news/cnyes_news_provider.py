from datetime import datetime, timezone
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup

from a_domain.model.market.article import Article
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import ContentType, InformationSource


class CnyesNewsProvider:
    def __init__(self, logger: ILoggingProvider):
        self._logger = logger
        self._api_url = "https://api.cnyes.com/media/api/v1/search"

    async def fetch_news(self, stock_id: str, limit: int) -> list[Article]:
        self._logger.debug(f"Fetching Cnyes News for {stock_id} via API...")
        params = {"q": stock_id, "limit": limit}

        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            try:
                resp = await client.get(self._api_url, params=params)
                resp.raise_for_status()

                data = resp.json()
                items = data.get("items", {}).get("data", [])

                articles: list[Article] = []
                for item in items:
                    title = item.get("title", "").strip()

                    # Extract content (HTML) and clean it
                    raw_content = item.get("content", "")
                    summary = item.get("summary", "").strip()

                    if raw_content:
                        clean_content = BeautifulSoup(raw_content, "html.parser").get_text(separator="\n", strip=True)
                    else:
                        clean_content = summary

                    if stock_id not in title and stock_id not in clean_content:
                        continue

                    publish_at_ts = item.get("publishAt")
                    pub_date = datetime.fromtimestamp(publish_at_ts, tz=timezone.utc) if publish_at_ts else datetime.now(timezone.utc)
                    news_id = item.get("newsId", "")

                    articles.append(
                        Article(
                            id=uuid4(),
                            stock_id=stock_id,
                            source=InformationSource.NEWS_MEDIA,
                            title=title,
                            content=clean_content,
                            url=f"https://news.cnyes.com/news/id/{news_id}",
                            content_type=ContentType.REPORT,
                            published_at=pub_date,
                            fetched_at=datetime.now(timezone.utc),
                        )
                    )

                self._logger.info(f"Successfully fetched {len(articles)} Cnyes articles for {stock_id}.")
                return articles
            except Exception as e:
                self._logger.error(f"Unexpected error parsing Cnyes API for {stock_id}: {e}")
                return []
