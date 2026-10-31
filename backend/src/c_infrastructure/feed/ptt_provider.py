import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import override

import httpx
from bs4 import BeautifulSoup, Tag

from a_domain.model.market.article import Article
from a_domain.model.market.post_listing import PostListing
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import ContentType, InformationSource
from b_application.config.app_config import AppConfig
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE


class PttProvider(ISocialMediaProvider):
    """
    PTT Stock board scraper. Searches /bbs/Stock/search?q=<tag> and pages back until the date cutoff
    is reached or enough articles are collected.
    """

    def __init__(self, config: AppConfig, logger: ILoggingProvider, stock_provider: IStockProvider) -> None:
        self._config = config
        self._ptt = config.sources.ptt
        self._logger = logger
        self._stock_provider = stock_provider
        self._stock_ids: set[str] | None = None
        self._search_url = config.sources.ptt.base_url + config.sources.ptt.search_path
        self._ticker_label = re.compile(config.sources.ptt.ticker_label_pattern)
        self._ticker_parenthesized = re.compile(config.sources.ptt.ticker_parenthesized_pattern)
        self._title_ticker = re.compile(config.sources.ptt.title_ticker_pattern)
        headers = {"User-Agent": config.sources.ptt.user_agent, "Cookie": config.sources.ptt.cookie}
        self._client = httpx.AsyncClient(timeout=config.sources.ptt.timeout_seconds, headers=headers, follow_redirects=True)

    @override
    async def fetch_social_articles(self, limit: int) -> list[Article]:
        self._logger.info("Scanning PTT Stock board...")

        if self._stock_ids is None:
            self._logger.debug("Loading TWSE/TPEX universe...")
            self._stock_ids = {stock.stock_id for stock in await self._stock_provider.get_all()}

        since = datetime.now().date() - timedelta(days=self._config.collect_rules.ptt_lookback_days)
        articles: list[Article] = []

        for tag in self._config.collect_rules.ptt_tags:
            if len(articles) >= limit:
                break

            articles.extend(await self.fetch_tag_articles(tag, self._stock_ids, since, limit - len(articles)))

        unique_articles = {article.url or str(article.id): article for article in articles}
        result = list(unique_articles.values())[:limit]
        self._logger.info(f"PTT scan complete. {len(result)} unique articles.")
        return result

    @override
    def save_social_media_data(self, articles: list[Article]) -> None:
        if not articles:
            return

        current_time = datetime.now()
        archive_directory = self._config.project_root / self._config.folder.buzz_archive_dir / current_time.strftime("%Y-%m-%d")
        archive_directory.mkdir(parents=True, exist_ok=True)
        archive_path = archive_directory / f"ptt_buzz_{current_time.strftime('%H%M%S')}.md"

        try:
            with archive_path.open("w", encoding="utf-8") as archive_file:
                archive_file.write(f"# PTT Buzz — {current_time:%Y-%m-%d %H:%M}\n\n")

                for index, article in enumerate(articles, 1):
                    archive_file.write(
                        f"## [{index}] {article.stock_id}: {article.title}\n"
                        f"- {article.source.value} | {article.url}\n\n"
                        f"> {article.content[: self._ptt.archive_excerpt_length]}\n\n---\n\n"
                    )

            self._logger.trace(f"Buzz archive saved → {archive_path}")
        except OSError as error:
            self._logger.error(f"Buzz archive write failed: {error}")

    @override
    async def fetch_tag_articles(self, tag: str, stock_ids: set[str], since: date, limit: int) -> list[Article]:
        articles: list[Article] = []
        url, params = self._search_url, {"q": tag}

        for _ in range(self._ptt.max_pages):
            page = await self.fetch_page(url, params)

            if page is None:
                break

            listings = self.parse_listings(page)

            for listing in (listing for listing in listings if listing.posted_on >= since):
                article_page = await self.fetch_page(listing.url)
                article = None if article_page is None else self.parse_article(article_page, listing, stock_ids)

                if article is not None:
                    articles.append(article)

                if len(articles) >= limit:
                    return articles

            next_url = self.previous_page_url(page)

            if next_url is None or any(listing.posted_on < since for listing in listings):
                break

            url, params = next_url, None

        return articles

    @override
    async def fetch_page(self, url: str, params: Mapping[str, str] | None = None) -> str | None:
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as error:
            self._logger.warning(f"PTT request failed: {error}")
            return None

    @override
    def parse_listings(self, page: str) -> list[PostListing]:
        today = datetime.now().date()
        listings: list[PostListing] = []

        for row in BeautifulSoup(page, "html.parser").select("div.r-ent"):
            anchor = row.find("a")
            href = anchor.get("href", "") if isinstance(anchor, Tag) else ""

            if not isinstance(anchor, Tag) or not isinstance(href, str) or not href:
                continue

            date_element = row.find("div", class_="date")
            month_day = date_element.get_text(strip=True) if isinstance(date_element, Tag) else ""
            posted_on = today

            try:
                month, day = (int(part) for part in month_day.split("/")[:2])
                posted_on = date(today.year if month <= today.month else today.year - 1, month, day)
            except ValueError:
                pass

            listings.append(PostListing(title=anchor.get_text(strip=True), url=self._ptt.base_url + href, posted_on=posted_on))

        return listings

    @override
    def previous_page_url(self, page: str) -> str | None:
        paging = BeautifulSoup(page, "html.parser").find("div", class_="btn-group-paging")

        if not isinstance(paging, Tag):
            return None

        for anchor in paging.find_all("a"):
            href = anchor.get("href", "")

            if self._ptt.previous_page_label in anchor.get_text() and isinstance(href, str) and href:
                return self._ptt.base_url + href

        return None

    @override
    def parse_article(self, page: str, listing: PostListing, stock_ids: set[str]) -> Article | None:
        main_content = BeautifulSoup(page, "html.parser").find("div", id="main-content")

        if not isinstance(main_content, Tag):
            return None

        stock_id = self.extract_stock_id(main_content.get_text(separator="\n", strip=True), listing.title)

        if stock_id is None or stock_id not in stock_ids:
            return None

        reactions = [
            tag.get_text().strip()
            for push in main_content.find_all("div", class_="push")
            if (tag := push.find("span", class_="push-tag"))
        ]

        for element in main_content.find_all("div", class_=["push", "article-metaline", "article-metaline-right"]):
            element.decompose()

        return self.to_article(stock_id, listing, reactions, main_content.get_text(separator="\n", strip=True))

    @override
    def to_article(self, stock_id: str, listing: PostListing, reactions: list[str], text: str) -> Article | None:
        content = self.clean_content(text)

        if not content:
            return None

        push_count, boo_count, arrow_count = (
            reactions.count(tag) for tag in (self._ptt.push_tag, self._ptt.boo_tag, self._ptt.arrow_tag)
        )
        reaction_header = f"[{push_count}{self._ptt.push_tag} {boo_count}{self._ptt.boo_tag} {arrow_count}{self._ptt.arrow_tag}]"

        return Article(
            stock_id=stock_id,
            source=InformationSource.PTT_STOCK,
            title=listing.title,
            content=f"{reaction_header}\n{content}"[: self._ptt.max_body_length],
            url=listing.url,
            content_type=ContentType.ANALYSIS,
            published_at=datetime.combine(listing.posted_on, datetime.min.time(), tzinfo=TAIWAN_TIMEZONE),
            fetched_at=datetime.now(UTC),
            engagement=push_count + boo_count + arrow_count,
            raw_metadata={"push": push_count, "boo": boo_count, "arrow": arrow_count},
        )

    @override
    def extract_stock_id(self, body: str, title: str) -> str | None:
        template_match = self._ticker_label.search(body)

        if template_match:
            return template_match.group(1)

        for stock_id in self._ticker_parenthesized.findall(body):
            if not stock_id.startswith("0"):
                return stock_id

        title_match = self._title_ticker.search(title)
        return title_match.group(1) if title_match else None

    @override
    def clean_content(self, text: str) -> str:
        lines = [line.strip() for line in text.split("\n")]
        kept = [
            line
            for line in lines
            if line and not line.startswith("※") and self._ptt.posting_reminder_marker not in line and "ctrl+y" not in line.lower()
        ]
        return "\n".join(kept).strip()
