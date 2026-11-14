import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import override

import httpx
from bs4 import BeautifulSoup, Tag

from a_domain.model.market.article import Article
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import ContentType, InformationSource
from b_application.config.app_config import AppConfig
from b_application.config.sources_config import PttSources
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

type TickerPatterns = tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]
"""Where a post names its stock: its ticker line, an id in parentheses, an id in its title."""


@dataclass(frozen=True, kw_only=True)
class PostListing:
    """A social post as a board's listing shows it, before its page is read."""

    title: str
    url: str
    posted_on: date


class PttProvider(ISocialMediaProvider):
    """
    PTT Stock board scraper. Searches /bbs/Stock/search?q=<tag> and pages back until the date cutoff
    is reached or enough articles are collected. The board dates a post by its Taipei month and day, so every day here
    is the market clock's, whatever zone the server runs in.
    """

    def __init__(
        self, config: AppConfig, logger: ILoggingProvider, stock_provider: IStockProvider, market_clock: IMarketClock
    ) -> None:
        self._config = config
        self._market_clock = market_clock
        self._ptt = config.sources.ptt
        self._logger = logger
        self._stock_provider = stock_provider
        self._stock_ids: set[str] | None = None
        self._search_url = config.sources.ptt.base_url + config.sources.ptt.search_path
        self._tickers: TickerPatterns = (
            re.compile(config.sources.ptt.ticker_label_pattern),
            re.compile(config.sources.ptt.ticker_parenthesized_pattern),
            re.compile(config.sources.ptt.title_ticker_pattern),
        )
        headers = {"User-Agent": config.sources.ptt.user_agent, "Cookie": config.sources.ptt.cookie}
        self._client = httpx.AsyncClient(timeout=config.sources.ptt.timeout_seconds, headers=headers, follow_redirects=True)

    @override
    async def fetch_social_articles(self, limit: int) -> list[Article]:
        self._logger.info("Scanning PTT Stock board...")

        if self._stock_ids is None:
            self._logger.debug("Loading TWSE/TPEX universe...")
            self._stock_ids = {stock.stock_id for stock in await self._stock_provider.get_all()}

        since = self._market_clock.today() - timedelta(days=self._config.collect_rules.ptt_lookback_days)
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
    async def fetch_stock_posts(self, stock_id: str, limit: int) -> list[Article]:
        page = await fetch_page(self._client, self._logger, self._search_url, {"q": stock_id})
        now = self._market_clock.now()

        return [
            Article(
                stock_id=stock_id,
                source=InformationSource.PTT_STOCK,
                title=listing.title,
                content="",
                url=listing.url,
                published_at=datetime.combine(listing.posted_on, datetime.min.time(), tzinfo=TAIWAN_TIMEZONE),
                fetched_at=now,
            )
            for listing in parse_listings(page or "", self._ptt, self._market_clock)[:limit]
        ]

    @override
    def save_social_media_data(self, articles: list[Article]) -> None:
        if not articles:
            return

        current_time = self._market_clock.now()
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
            page = await fetch_page(self._client, self._logger, url, params)

            if page is None:
                break

            listings = parse_listings(page, self._ptt, self._market_clock)

            for listing in (listing for listing in listings if listing.posted_on >= since):
                article_page = await fetch_page(self._client, self._logger, listing.url)
                article = parse_article(article_page or "", listing, stock_ids, self._tickers, self._ptt, self._market_clock)

                if article is not None:
                    articles.append(article)

                if len(articles) >= limit:
                    return articles

            next_url = previous_page_url(page, self._ptt)

            if next_url is None or any(listing.posted_on < since for listing in listings):
                break

            url, params = next_url, None

        return articles


async def fetch_page(
    client: httpx.AsyncClient, logger: ILoggingProvider, url: str, params: Mapping[str, str] | None = None
) -> str | None:
    """The text of a board page, or None when the board could not be read."""
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as error:
        logger.warning(f"PTT request failed: {error}")
        return None


def parse_listings(page: str, ptt: PttSources, clock: IMarketClock) -> list[PostListing]:
    """The posts a search page lists, in its order."""
    today = clock.today()
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

        listings.append(PostListing(title=anchor.get_text(strip=True), url=ptt.base_url + href, posted_on=posted_on))

    return listings


def previous_page_url(page: str, ptt: PttSources) -> str | None:
    """The search page with the older posts, or None on the last page."""
    paging = BeautifulSoup(page, "html.parser").find("div", class_="btn-group-paging")

    if not isinstance(paging, Tag):
        return None

    for anchor in paging.find_all("a"):
        href = anchor.get("href", "")

        if ptt.previous_page_label in anchor.get_text() and isinstance(href, str) and href:
            return ptt.base_url + href

    return None


def parse_article(
    page: str, listing: PostListing, stock_ids: set[str], tickers: TickerPatterns, ptt: PttSources, clock: IMarketClock
) -> Article | None:
    """The post on its page, or None when it names no stock in stock_ids or has no text."""
    main_content = BeautifulSoup(page, "html.parser").find("div", id="main-content")

    if not isinstance(main_content, Tag):
        return None

    stock_id = extract_stock_id(main_content.get_text(separator="\n", strip=True), listing.title, tickers)

    if stock_id is None or stock_id not in stock_ids:
        return None

    reactions = [
        tag.get_text().strip() for push in main_content.find_all("div", class_="push") if (tag := push.find("span", class_="push-tag"))
    ]

    for element in main_content.find_all("div", class_=["push", "article-metaline", "article-metaline-right"]):
        element.decompose()

    return to_article(stock_id, listing, reactions, main_content.get_text(separator="\n", strip=True), ptt, clock)


def to_article(
    stock_id: str, listing: PostListing, reactions: list[str], text: str, ptt: PttSources, clock: IMarketClock
) -> Article | None:
    """The post as an article, its cleaned text headed by its reaction counts, or None when no text is left."""
    content = clean_content(text, ptt)

    if not content:
        return None

    push_count, boo_count, arrow_count = (reactions.count(tag) for tag in (ptt.push_tag, ptt.boo_tag, ptt.arrow_tag))
    reaction_header = f"[{push_count}{ptt.push_tag} {boo_count}{ptt.boo_tag} {arrow_count}{ptt.arrow_tag}]"

    return Article(
        stock_id=stock_id,
        source=InformationSource.PTT_STOCK,
        title=listing.title,
        content=f"{reaction_header}\n{content}"[: ptt.max_body_length],
        url=listing.url,
        content_type=ContentType.ANALYSIS,
        published_at=datetime.combine(listing.posted_on, datetime.min.time(), tzinfo=TAIWAN_TIMEZONE),
        fetched_at=clock.now(),
        engagement=push_count + boo_count + arrow_count,
        raw_metadata={"push": push_count, "boo": boo_count, "arrow": arrow_count},
    )


def extract_stock_id(body: str, title: str, tickers: TickerPatterns) -> str | None:
    """The stock a post is about: its ticker line, else a parenthesized id, else an id in its title."""
    ticker_label, ticker_parenthesized, title_ticker = tickers
    template_match = ticker_label.search(body)

    if template_match:
        return template_match.group(1)

    for stock_id in ticker_parenthesized.findall(body):
        if not stock_id.startswith("0"):
            return stock_id

    title_match = title_ticker.search(title)
    return title_match.group(1) if title_match else None


def clean_content(text: str, ptt: PttSources) -> str:
    """The post's text without the board's signature, reminder and blank lines."""
    lines = [line.strip() for line in text.split("\n")]
    kept = [
        line
        for line in lines
        if line and not line.startswith("※") and ptt.posting_reminder_marker not in line and "ctrl+y" not in line.lower()
    ]
    return "\n".join(kept).strip()
