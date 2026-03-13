from datetime import datetime
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
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

    async def fetch_news(self, stock_id: str, limit: int = 5) -> list[Article]:
        # TODO: Delete this limit?
        # I need to think about whole of limitation's logic
        self._logger.debug(f"Fetching Yahoo TW News for {stock_id}...")
        url = f"https://tw.stock.yahoo.com/quote/{stock_id}.TW/news"

        async with httpx.AsyncClient(timeout=15.0, headers=self._headers, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "lxml")
                articles: list[Article] = []

                news_items = soup.find_all("li", class_="js-stream-content")

                for item in news_items:
                    if len(articles) >= limit:
                        break

                    title_tag = item.find("a", class_="js-content-viewer")
                    if not title_tag:
                        continue

                    title = title_tag.get_text(strip=True)

                    # [FIX]: Type safety for BeautifulSoup attributes
                    href_val = title_tag.get("href")
                    link = str(href_val[0]) if isinstance(href_val, list) else str(href_val or "")

                    summary_tag = item.find("p")
                    content = summary_tag.get_text(strip=True) if summary_tag else title

                    time_tag = item.find("time")
                    pub_date = datetime.now()

                    if time_tag:
                        dt_val = time_tag.get("datetime")
                        pub_date_str = str(dt_val[0]) if isinstance(dt_val, list) else str(dt_val or "")
                        if pub_date_str:
                            try:
                                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                            except ValueError:
                                pass

                    article = Article(
                        id=uuid4(),
                        stock_id=stock_id,
                        source=InformationSource.NEWS_MEDIA,
                        title=title,
                        content=content,
                        url=link,
                        content_type=ContentType.REPORT,
                        published_at=pub_date,
                        fetched_at=datetime.now(),
                    )
                    articles.append(article)

                self._logger.info(f"Successfully scraped {len(articles)} articles for {stock_id}.")
                return articles

            except httpx.RequestError as e:
                self._logger.error(f"HTTP Error fetching news for {stock_id}: {e}")
                return []  # [FIX]: Return empty list instead of None
            except Exception as e:
                self._logger.error(f"Unexpected error parsing Yahoo News for {stock_id}: {e}")
                return []  # [FIX]: Return empty list instead of None
