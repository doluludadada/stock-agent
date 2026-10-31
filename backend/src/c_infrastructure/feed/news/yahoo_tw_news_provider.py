import asyncio
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


class YahooTwNewsProvider(INewsSource):
    def __init__(self, news: NewsSources, logger: ILoggingProvider):
        self._news = news
        self._logger = logger
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self._client = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": user_agent}, follow_redirects=True, verify=False)

    @override
    async def fetch_news(self, stock_id: str, limit: int) -> list[Article]:
        """The stock's Yahoo news page lists headlines; each article's page gives its text, else the headline stands in."""
        self._logger.debug(f"Fetching Yahoo TW News for {stock_id}...")
        page = await self.fetch_page(f"{self._news.yahoo_quote_url}{stock_id}/news")

        if page is None:
            return []

        articles = self.parse_listing(stock_id, page)[:limit]
        bodies = await asyncio.gather(*(self.fetch_article_body(str(article.url)) for article in articles), return_exceptions=True)

        for article, body in zip(articles, bodies, strict=True):
            article.content = body if isinstance(body, str) and body else article.title

        self._logger.info(f"Successfully scraped {len(articles)} articles with content for {stock_id} from Yahoo.")
        return articles

    @override
    async def fetch_page(self, url: str, params: Mapping[str, str | int] | None = None) -> str | None:
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.text
        except Exception as error:
            self._logger.error(f"Unexpected error reading Yahoo News page {url}: {error}")
            return None

    @override
    def parse_listing(self, stock_id: str, page: str) -> list[Article]:
        """Each news link with a headline of at least 5 characters, once per URL. A URL's first link decides its headline."""
        links = BeautifulSoup(page, "lxml").find_all("a", href=lambda href: bool(href) and "/news/" in href and ".html" in href)
        headlines: dict[str, str] = {}

        for link in links:
            href = link.get("href")
            headlines.setdefault(str(href[0]) if isinstance(href, list) else str(href or ""), link.get_text(strip=True))

        now = datetime.now(UTC)

        return [
            Article(
                id=uuid4(),
                stock_id=stock_id,
                source=InformationSource.NEWS_MEDIA,
                title=title,
                content="",
                url=href if href.startswith("http") else f"{self._news.yahoo_base_url}{href}",
                content_type=ContentType.REPORT,
                published_at=now,
                fetched_at=now,
            )
            for href, title in headlines.items()
            if len(title) >= 5
        ]

    @override
    async def fetch_article_body(self, url: str) -> str:
        """Yahoo wraps an article's text in caas-body; without it, the page's paragraphs of more than 20 characters."""
        try:
            response = await self._client.get(url)

            if response.status_code != 200:
                return ""

            soup = BeautifulSoup(response.text, "lxml")
            body = soup.find("div", class_="caas-body")

            if body:
                return body.get_text(separator="\n", strip=True)

            paragraphs = [paragraph.get_text(strip=True) for paragraph in soup.find_all("p")]
            return "\n".join(paragraph for paragraph in paragraphs if len(paragraph) > 20)
        except Exception as error:
            self._logger.debug(f"Failed to fetch Yahoo body for {url}: {error}")
            return ""
