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
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

    async def fetch_news(self, stock_id: str, limit: int) -> list[Article]:
        self._logger.debug(f"Fetching Yahoo TW News for {stock_id}...")
        url = f"https://tw.stock.yahoo.com/quote/{stock_id}/news"

        async with httpx.AsyncClient(timeout=15.0, headers=self._headers, follow_redirects=True, verify=False) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "lxml")
                articles: list[Article] = []

                def is_valid_news_link(href: str | None) -> bool:
                    if not href:
                        return False
                    return "/news/" in href and ".html" in href

                news_links = soup.find_all("a", href=is_valid_news_link)

                seen_urls = set()
                for link in news_links:
                    if len(articles) >= limit:
                        break

                    href = link.get("href")
                    href_str = str(href[0]) if isinstance(href, list) else str(href or "")

                    if href_str in seen_urls:
                        continue
                    seen_urls.add(href_str)

                    title = link.get_text(strip=True)
                    if not title or len(title) < 5:
                        continue

                    articles.append(
                        Article(
                            id=uuid4(),
                            stock_id=stock_id,
                            source=InformationSource.NEWS_MEDIA,
                            title=title,
                            content=title,
                            url=href_str if href_str.startswith("http") else f"https://tw.stock.yahoo.com{href_str}",
                            content_type=ContentType.REPORT,
                            published_at=datetime.now(timezone.utc),
                            fetched_at=datetime.now(timezone.utc),
                        )
                    )

                self._logger.info(f"Successfully scraped {len(articles)} articles for {stock_id} from Yahoo.")
                return articles

            except httpx.RequestError as e:
                self._logger.error(f"HTTP Error fetching news for {stock_id}: {e}")
                return []
            except Exception as e:
                self._logger.error(f"Unexpected error parsing Yahoo News for {stock_id}: {e}")
                return []
