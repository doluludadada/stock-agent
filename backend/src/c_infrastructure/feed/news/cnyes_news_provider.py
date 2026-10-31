import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup

from a_domain.model.market.article import Article
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import ContentType, InformationSource
from b_application.config.sources_config import NewsSources


class CnyesNewsProvider:
    def __init__(self, news: NewsSources, logger: ILoggingProvider):
        self._logger = logger
        self._base_url = news.cnyes_api_url
        self._article_url = news.cnyes_article_url
        self._headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

    async def fetch_news(self, stock_id: str, limit: int) -> list[Article]:
        self._logger.debug(f"Fetching Cnyes News for {stock_id}...")

        async with httpx.AsyncClient(timeout=10.0, headers=self._headers, verify=False) as client:
            # Cnyes search returns HTTP 500 for some bare Taiwan stock ids such as 2486.
            # The stock page uses this symbolNews endpoint, which is the cleaner source for stock-specific news.
            for url, params in (
                (f"{self._base_url}/newslist/TWS:{stock_id}:STOCK/symbolNews", {"page": 1, "limit": limit}),
                (f"{self._base_url}/newslist/TWO:{stock_id}:STOCK/symbolNews", {"page": 1, "limit": limit}),
                (f"{self._base_url}/search", {"q": stock_id, "limit": limit}),
            ):
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    items = resp.json().get("items", {}).get("data", [])
                    articles = []

                    for item in items:
                        title = str(item.get("title", "")).strip()
                        raw_content = str(item.get("content", ""))
                        summary = str(item.get("summary", "")).strip()
                        content = (
                            BeautifulSoup(raw_content, "html.parser").get_text(separator="\n", strip=True) if raw_content else summary
                        )

                        if url.endswith("/search") and stock_id not in f"{title}\n{content}":
                            continue

                        publish_at = item.get("publishAt")
                        published_at = datetime.fromtimestamp(publish_at, tz=UTC) if publish_at else datetime.now(UTC)
                        news_id = item.get("newsId", "")

                        articles.append(
                            Article(
                                id=uuid4(),
                                stock_id=stock_id,
                                source=InformationSource.NEWS_MEDIA,
                                title=title,
                                content=content,
                                url=f"{self._article_url}{news_id}",
                                content_type=ContentType.REPORT,
                                published_at=published_at,
                                fetched_at=datetime.now(UTC),
                            )
                        )

                    # symbolNews lists headlines only, so read the missing bodies from the article pages.
                    missing_body = [article for article in articles if not article.content]
                    bodies = await asyncio.gather(*(self._fetch_article_body(client, str(article.url)) for article in missing_body))
                    for article, body in zip(missing_body, bodies, strict=True):
                        article.content = body

                    if articles:
                        self._logger.info(f"Successfully fetched {len(articles)} Cnyes articles for {stock_id}.")
                        return articles[:limit]
                except httpx.HTTPStatusError as error:
                    status_code = error.response.status_code
                    if status_code >= 500:
                        self._logger.warning(f"Cnyes endpoint unavailable for {stock_id} (HTTP {status_code}); trying next source.")
                    else:
                        self._logger.error(f"Cnyes rejected request for {stock_id} (HTTP {status_code}): {error}")
                except httpx.RequestError as error:
                    self._logger.warning(f"Cnyes request failed for {stock_id}: {error}")
                except Exception as error:
                    self._logger.error(f"Unexpected error parsing Cnyes response for {stock_id}: {error}")

        self._logger.warning(f"No Cnyes articles found for {stock_id}.")
        return []

    async def _fetch_article_body(self, client: httpx.AsyncClient, url: str) -> str:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as error:
            self._logger.debug(f"Failed to fetch Cnyes body for {url}: {error!r}")
            return ""

        body = BeautifulSoup(resp.text, "html.parser").select_one("#article-container")
        return body.get_text(separator="\n", strip=True) if body else ""
