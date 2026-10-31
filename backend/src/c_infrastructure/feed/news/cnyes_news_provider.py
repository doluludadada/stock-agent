import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import override
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup

from a_domain.model.market.article import Article
from a_domain.ports.market.news_source import INewsSource
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import ContentType, InformationSource
from b_application.config.sources_config import NewsSources


class CnyesNewsProvider(INewsSource):
    def __init__(self, news: NewsSources, logger: ILoggingProvider):
        self._logger = logger
        self._base_url = news.cnyes_api_url
        self._article_url = news.cnyes_article_url
        self._client = httpx.AsyncClient(
            timeout=10.0, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"}, verify=False
        )

    @override
    async def fetch_news(self, stock_id: str, limit: int) -> list[Article]:
        """
        Cnyes search returns HTTP 500 for some bare Taiwan stock ids such as 2486, so the listed and OTC symbolNews feeds
        the stock page uses come first, and search, which also finds articles that only mention the id, comes last.
        """
        self._logger.debug(f"Fetching Cnyes News for {stock_id}...")
        feeds = (
            (f"{self._base_url}/newslist/TWS:{stock_id}:STOCK/symbolNews", {"page": 1, "limit": limit}),
            (f"{self._base_url}/newslist/TWO:{stock_id}:STOCK/symbolNews", {"page": 1, "limit": limit}),
            (f"{self._base_url}/search", {"q": stock_id, "limit": limit}),
        )

        for url, params in feeds:
            page = await self.fetch_page(url, params)
            from_search = url.endswith("/search")
            articles = [] if page is None else self.parse_listing(stock_id, page)
            articles = [article for article in articles if not from_search or stock_id in f"{article.title}\n{article.content}"]
            # symbolNews lists headlines only, so read the missing bodies from the article pages.
            missing_body = [article for article in articles if not article.content]
            bodies = await asyncio.gather(*(self.fetch_article_body(str(article.url)) for article in missing_body))

            for article, body in zip(missing_body, bodies, strict=True):
                article.content = body

            if articles:
                self._logger.info(f"Successfully fetched {len(articles)} Cnyes articles for {stock_id}.")
                return articles[:limit]

        self._logger.warning(f"No Cnyes articles found for {stock_id}.")
        return []

    @override
    async def fetch_page(self, url: str, params: Mapping[str, str | int] | None = None) -> str | None:
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code

            if status_code >= 500:
                self._logger.warning(f"Cnyes endpoint {url} unavailable (HTTP {status_code}); trying next source.")
            else:
                self._logger.error(f"Cnyes rejected request {url} (HTTP {status_code}): {error}")

            return None
        except httpx.RequestError as error:
            self._logger.warning(f"Cnyes request {url} failed: {error}")
            return None

    @override
    def parse_listing(self, stock_id: str, page: str) -> list[Article]:
        try:
            items = json.loads(page).get("items", {}).get("data", [])
        except (ValueError, AttributeError) as error:
            self._logger.error(f"Unexpected Cnyes response for {stock_id}: {error}")
            return []

        articles: list[Article] = []

        for item in items:
            raw_content = str(item.get("content", ""))
            publish_at = item.get("publishAt")
            text = BeautifulSoup(raw_content, "html.parser").get_text(separator="\n", strip=True) if raw_content else ""
            articles.append(
                Article(
                    id=uuid4(),
                    stock_id=stock_id,
                    source=InformationSource.NEWS_MEDIA,
                    title=str(item.get("title", "")).strip(),
                    content=text or str(item.get("summary", "")).strip(),
                    url=f"{self._article_url}{item.get('newsId', '')}",
                    content_type=ContentType.REPORT,
                    published_at=datetime.fromtimestamp(publish_at, tz=UTC) if publish_at else datetime.now(UTC),
                    fetched_at=datetime.now(UTC),
                )
            )

        return articles

    @override
    async def fetch_article_body(self, url: str) -> str:
        try:
            response = await self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as error:
            self._logger.debug(f"Failed to fetch Cnyes body for {url}: {error!r}")
            return ""

        body = BeautifulSoup(response.text, "html.parser").select_one("#article-container")
        return body.get_text(separator="\n", strip=True) if body else ""
