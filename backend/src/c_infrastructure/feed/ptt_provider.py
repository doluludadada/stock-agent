# backend/src/c_infrastructure/feed/ptt_provider.py
# Current source: :contentReference[oaicite:4]{index=4}

import re
from datetime import date, datetime, timedelta
from typing import TypedDict

import httpx
from bs4 import BeautifulSoup, Tag

from a_domain.model.market.article import Article
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import ContentType, InformationSource
from b_application.schemas.config import AppConfig


class PttListing(TypedDict):
    title: str
    url: str
    published_date: date


# ---------------------------------- parsing ---------------------------------- #


class PttParser:
    RE_TICKER_TEMPLATE = re.compile(r"股票代碼[^:：]*[:：]\s*(\d{4})")
    RE_TICKER_PARENS = re.compile(r"[（(](\d{4})[)）]")
    RE_TICKER_TITLE = re.compile(r"(\d{4})")

    def __init__(self, base_url: str, max_body_length: int) -> None:
        self._base_url = base_url
        self._max_body_length = max_body_length

    def parse_listing(self, row: Tag) -> PttListing | None:
        anchor = row.find("a")
        if anchor is None:
            return None

        href = anchor.get("href", "")
        if not isinstance(href, str) or not href:
            return None

        published_date = datetime.now().date()
        date_element = row.find("div", class_="date")
        if isinstance(date_element, Tag):
            parts = date_element.get_text(strip=True).split("/")
            try:
                month, day = int(parts[0]), int(parts[1])
                year = published_date.year if month <= published_date.month else published_date.year - 1
                published_date = date(year, month, day)
            except ValueError:
                pass
            except IndexError:
                pass

        return PttListing(title=anchor.get_text(strip=True), url=self._base_url + href, published_date=published_date)

    def parse_article(self, html: str, listing: PttListing, stock_universe: set[str]) -> Article | None:
        main_content = BeautifulSoup(html, "html.parser").find("div", id="main-content")
        if not isinstance(main_content, Tag):
            return None

        body_text = main_content.get_text(separator="\n", strip=True)
        stock_id = self.extract_stock_id(body_text, listing["title"])
        if stock_id is None or stock_id not in stock_universe:
            return None

        push_count, boo_count, arrow_count = self.count_engagement(main_content)
        content = self.clean_content(main_content)
        if not content:
            return None

        engagement = push_count + boo_count + arrow_count
        content = f"[{push_count}推 {boo_count}噓 {arrow_count}→]\n{content}"
        content = content[: self._max_body_length]

        return Article(
            stock_id=stock_id,
            source=InformationSource.PTT_STOCK,
            title=listing["title"],
            content=content,
            url=listing["url"],
            content_type=ContentType.ANALYSIS,
            published_at=datetime.combine(listing["published_date"], datetime.min.time()),
            raw_metadata={"engagement": engagement, "push": push_count, "boo": boo_count, "arrow": arrow_count},
        )

    def extract_stock_id(self, body: str, title: str) -> str | None:
        template_match = self.RE_TICKER_TEMPLATE.search(body)
        if template_match:
            return template_match.group(1)

        for stock_id in self.RE_TICKER_PARENS.findall(body):
            if not stock_id.startswith("0"):
                return stock_id

        title_match = self.RE_TICKER_TITLE.search(title)
        return title_match.group(1) if title_match else None

    def count_engagement(self, main_content: Tag) -> tuple[int, int, int]:
        push_count = 0
        boo_count = 0
        arrow_count = 0

        for push_element in main_content.find_all("div", class_="push"):
            tag_element = push_element.find("span", class_="push-tag")
            if tag_element is None:
                continue

            push_tag = tag_element.get_text().strip()
            if push_tag == "推":
                push_count += 1
            elif push_tag == "噓":
                boo_count += 1
            elif push_tag == "→":
                arrow_count += 1

        return push_count, boo_count, arrow_count

    def clean_content(self, main_content: Tag) -> str:
        for class_name in ("push", "article-metaline", "article-metaline-right"):
            for element in main_content.find_all("div", class_=class_name):
                element.decompose()

        lines: list[str] = []
        for raw_line in main_content.get_text(separator="\n", strip=True).split("\n"):
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("※"):
                continue

            if "發文提醒" in line or "ctrl+y" in line.lower():
                continue

            lines.append(line)

        return "\n".join(lines).strip()

    def previous_page_url(self, page: BeautifulSoup) -> str | None:
        paging = page.find("div", class_="btn-group-paging")
        if paging is None:
            return None

        for anchor in paging.find_all("a"):
            if "上頁" not in anchor.get_text():
                continue

            href = anchor.get("href", "")
            if isinstance(href, str) and href:
                return self._base_url + href

        return None


class PttProvider(ISocialMediaProvider):
    """
    PTT Stock Board Scraper — search endpoint approach.

    Hits /bbs/Stock/search?q=<tag> and paginates backwards until the date
    cutoff is reached or enough articles are collected.
    """

    BASE_URL = "https://www.ptt.cc"
    SEARCH_URL = f"{BASE_URL}/bbs/Stock/search"
    MAX_PAGES = 30
    MAX_BODY_LEN = 3000

    HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"), "Cookie": "over18=1"}

    def __init__(self, config: AppConfig, logger: ILoggingProvider, stock_provider: IStockProvider) -> None:
        self._config = config
        self._logger = logger
        self._stock_provider = stock_provider
        self._stock_universe: set[str] | None = None
        self._parser = PttParser(base_url=self.BASE_URL, max_body_length=self.MAX_BODY_LEN)

    # ── public ────────────────────────────────────────────────────── #

    async def fetch_social_articles(self, limit: int) -> list[Article]:
        self._logger.info("Scanning PTT Stock board...")
        stock_universe = await self._get_stock_universe()
        lookback_days = self._config.collect_rules.ptt_lookback_days
        cutoff = datetime.now().date() - timedelta(days=lookback_days)
        articles: list[Article] = []

        async with httpx.AsyncClient(timeout=15.0, headers=self.HEADERS, follow_redirects=True, verify=False) as http_client:
            for tag in self._config.collect_rules.ptt_tags:
                remaining_limit = limit - len(articles)
                if remaining_limit <= 0:
                    break

                articles.extend(await self._fetch_tag_articles(http_client, tag, stock_universe, cutoff, remaining_limit))

        unique_articles = {article.url or str(article.id): article for article in articles}
        result = list(unique_articles.values())[:limit]
        self._logger.info(f"PTT scan complete. {len(result)} unique articles.")
        return result

    def save_social_media_data(self, articles: list[Article]) -> None:
        if not articles:
            return

        current_time = datetime.now()
        archive_directory = self._config.project_root / self._config.folder.buzz_archive_dir / current_time.strftime("%Y-%m-%d")
        archive_directory.mkdir(parents=True, exist_ok=True)
        archive_path = archive_directory / (f"ptt_buzz_{current_time.strftime('%H%M%S')}.md")

        try:
            with archive_path.open("w", encoding="utf-8") as archive_file:
                archive_file.write(f"# PTT Buzz — {current_time:%Y-%m-%d %H:%M}\n\n")
                for index, article in enumerate(articles, 1):
                    archive_file.write(
                        f"## [{index}] {article.stock_id}: {article.title}\n"
                        f"- {article.source.value} | {article.url}\n\n"
                        f"> {article.content[:500]}\n\n---\n\n"
                    )

            self._logger.trace(f"Buzz archive saved → {archive_path}")
        except OSError as error:
            self._logger.error(f"Buzz archive write failed: {error}")

    # --------------------------------- scraping --------------------------------- #

    async def _fetch_tag_articles(
        self, http_client: httpx.AsyncClient, tag: str, stock_universe: set[str], cutoff: date, limit: int
    ) -> list[Article]:
        articles: list[Article] = []
        next_url: str | None = None

        for _ in range(self.MAX_PAGES):
            url = next_url or self.SEARCH_URL
            params = None if next_url else {"q": tag}
            page_html = await self._fetch_html(http_client, url, params)
            if page_html is None:
                break

            page = BeautifulSoup(page_html, "html.parser")
            reached_cutoff = False

            for row in page.find_all("div", class_="r-ent"):
                if not isinstance(row, Tag):
                    continue

                listing = self._parser.parse_listing(row)
                if listing is None:
                    continue

                if listing["published_date"] < cutoff:
                    reached_cutoff = True
                    continue

                article_html = await self._fetch_html(http_client, listing["url"])
                if article_html is None:
                    continue

                article = self._parser.parse_article(article_html, listing, stock_universe)
                if article is not None:
                    articles.append(article)

                if len(articles) >= limit:
                    break

            if reached_cutoff or len(articles) >= limit:
                break

            next_url = self._parser.previous_page_url(page)
            if next_url is None:
                break

        return articles

    async def _fetch_html(self, http_client: httpx.AsyncClient, url: str, params: dict[str, str] | None = None) -> str | None:
        try:
            response = await http_client.get(url, params=params)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as error:
            self._logger.warning(f"PTT request failed: {error}")
            return None

    async def _get_stock_universe(self) -> set[str]:
        if self._stock_universe is not None:
            return self._stock_universe

        self._logger.debug("Loading TWSE/TPEX universe...")
        stocks = await self._stock_provider.get_all()
        self._stock_universe = {stock.stock_id for stock in stocks}

        return self._stock_universe
