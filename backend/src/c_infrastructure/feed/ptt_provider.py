import re
from datetime import datetime
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup

from a_domain.model.market.article import Article
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import ContentType, InformationSource
from b_application.schemas.config import AppConfig


class PttProvider(ISocialMediaProvider):
    """Scrapes PTT Stock board to find trending stock tickers using BeautifulSoup4."""

    PTT_BASE_URL = "https://www.ptt.cc"
    PTT_STOCK_URL = "https://www.ptt.cc/bbs/Stock/index.html"
    MAX_CONTENT_LENGTH = 1000  # ? Remove it later? I guess

    def __init__(self, config: AppConfig, logger: ILoggingProvider):
        self._config = config
        self._logger = logger
        self._cookies = {"over18": "1"}

    async def get_trending_stocks(self, limit: int) -> list[Article]:
        self._logger.info("Scanning PTT Stock board for trending posts...")
        tags = self._config.collect_rules.ptt_required_tags

        async with httpx.AsyncClient(timeout=15.0, cookies=self._cookies) as client:
            try:
                resp = await client.get(self.PTT_STOCK_URL)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                articles: list[Article] = []

                for div in soup.find_all("div", class_="r-ent"):
                    if len(articles) >= limit:
                        break

                    title_a = div.find("a")
                    if not title_a:
                        continue

                    title_text = title_a.get_text(strip=True)

                    if not any(tag in title_text for tag in tags):
                        continue

                    tickers = re.findall(r"\b[1-9]\d{3}\b", title_text)
                    if not tickers:
                        continue

                    stock_id = tickers[0]
                    article_url = self.PTT_BASE_URL + str(title_a["href"])

                    content = await self._fetch_article_content(client, article_url)
                    if not content:
                        continue

                    articles.append(
                        Article(
                            id=uuid4(),
                            stock_id=stock_id,
                            source=InformationSource.PTT_STOCK,
                            title=title_text,
                            content=content,
                            url=article_url,
                            content_type=ContentType.ANALYSIS,
                            published_at=datetime.now(),
                            fetched_at=datetime.now(),
                        )
                    )
                    self._logger.debug(f"Successfully scraped PTT content for {stock_id}.")

                return articles

            except Exception as e:
                self._logger.error(f"Unexpected error parsing PTT: {e}")
                return []

    async def _fetch_article_content(self, client: httpx.AsyncClient, url: str) -> str | None:
        """Fetch and clean a single PTT article page."""
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")
            main_content = soup.find("div", id="main-content")
            if not main_content:
                return None

            for push in main_content.find_all("div", class_="push"):
                push.decompose()

            raw_text = main_content.get_text(separator="\n", strip=True)

            if len(raw_text) > self.MAX_CONTENT_LENGTH:
                return raw_text[: self.MAX_CONTENT_LENGTH] + "..."
            return raw_text

        except Exception as e:
            self._logger.debug(f"Failed to fetch article content from {url}: {e}")
            return None
