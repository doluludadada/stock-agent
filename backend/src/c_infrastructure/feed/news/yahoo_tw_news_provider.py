import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup

from a_domain.model.market.article import Article
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import ContentType, InformationSource


class YahooTwNewsProvider:
    def __init__(self, logger: ILoggingProvider):
        self._logger = logger
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"  # noqa: E501
        }

    async def _fetch_article_body(self, client: httpx.AsyncClient, url: str) -> str:
        """Fetches the actual text content from a Yahoo News article page."""
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return ""

            soup = BeautifulSoup(resp.text, "lxml")
            # Yahoo News usually wraps the main content in caas-body
            body = soup.find("div", class_="caas-body")
            if body:
                return body.get_text(separator="\n", strip=True)

            # Fallback if caas-body is missing
            paragraphs = soup.find_all("p")
            return "\n".join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20])
        except Exception as e:
            self._logger.debug(f"Failed to fetch Yahoo body for {url}: {e}")
            return ""

    async def fetch_news(self, stock_id: str, limit: int) -> list[Article]:
        self._logger.debug(f"Fetching Yahoo TW News for {stock_id}...")
        url = f"https://tw.stock.yahoo.com/quote/{stock_id}/news"

        async with httpx.AsyncClient(timeout=15.0, headers=self._headers, follow_redirects=True, verify=False) as client:
            try:
                # 1. Fetch the news list page
                resp = await client.get(url)
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "lxml")

                def is_valid_news_link(href: str | None) -> bool:
                    if not href:
                        return False
                    return "/news/" in href and ".html" in href

                news_links = soup.find_all("a", href=is_valid_news_link)

                # 2. Extract unique URLs and Titles
                seen_urls = set()
                pending_articles = []

                for link in news_links:
                    if len(pending_articles) >= limit:
                        break

                    href = link.get("href")
                    href_str = str(href[0]) if isinstance(href, list) else str(href or "")

                    if href_str in seen_urls:
                        continue
                    seen_urls.add(href_str)

                    title = link.get_text(strip=True)
                    if not title or len(title) < 5:
                        continue

                    full_url = href_str if href_str.startswith("http") else f"https://tw.stock.yahoo.com{href_str}"
                    pending_articles.append({"title": title, "url": full_url})

                # 3. Concurrently fetch the article bodies
                fetch_tasks = [self._fetch_article_body(client, item["url"]) for item in pending_articles]
                bodies = await asyncio.gather(*fetch_tasks, return_exceptions=True)

                # 4. Assemble Article entities
                articles: list[Article] = []
                for item, body in zip(pending_articles, bodies):
                    content = body if isinstance(body, str) and body else item["title"]

                    articles.append(
                        Article(
                            id=uuid4(),
                            stock_id=stock_id,
                            source=InformationSource.NEWS_MEDIA,
                            title=item["title"],
                            content=content,
                            url=item["url"],
                            content_type=ContentType.REPORT,
                            published_at=datetime.now(timezone.utc),
                            fetched_at=datetime.now(timezone.utc),
                        )
                    )

                self._logger.info(f"Successfully scraped {len(articles)} articles with content for {stock_id} from Yahoo.")
                return articles

            except Exception as e:
                self._logger.error(f"Unexpected error parsing Yahoo News for {stock_id}: {e}")
                return []
