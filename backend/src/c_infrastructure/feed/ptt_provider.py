"""
PTT Stock Board Scraper.

Two-stream scraping via PTT search:
  - [標的] posts: structured stock picks (parse 股票代碼 from body)
  - [新聞] posts: financial news (parse CompanyName(NNNN) pattern)

Both streams: date-based pagination, push-score pre-filter,
engagement counting (推/噓/→), ticker validation against TWSE universe.
"""

import re
from datetime import date, datetime, timedelta
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup

from a_domain.model.market.article import Article
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import ContentType, InformationSource
from b_application.schemas.config import AppConfig


class PttProvider(ISocialMediaProvider):
    PTT_BASE_URL = "https://www.ptt.cc"
    PTT_SEARCH_URL = "https://www.ptt.cc/bbs/Stock/search"
    MAX_CONTENT_LENGTH = 1500

    # Ticker extraction patterns
    # Pattern 1: [標的] template → 股票代碼(股) : 2330 or 股票代碼(代號): 2330
    _TICKER_TEMPLATE_RE = re.compile(r"股票代碼[^:：]*[:：]\s*(\d{4})")
    # Pattern 2: News convention → 台積電(2330) or 聯發科（2454）
    _TICKER_PARENS_RE = re.compile(r"[\(（](\d{4})[\)）]")

    def __init__(self, config: AppConfig, logger: ILoggingProvider, stock_provider: IStockProvider):
        self._config = config
        self._logger = logger
        self._stock_provider = stock_provider
        self._universe_cache: set[str] | None = None
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": "over18=1",
        }

    # ---------------------------------------------------------------------------- #
    #                              Public Interface                                #
    # ---------------------------------------------------------------------------- #

    async def get_trending_stocks(self, limit: int) -> list[Article]:
        self._logger.info("Scanning PTT Stock board for trending posts...")
        tags = self._config.collect_rules.ptt_tags

        articles: list[Article] = []
        for tag in tags:
            tag_articles = await self._scrape_tag(tag, limit)
            articles.extend(tag_articles)

        # Deduplicate by URL
        seen: set[str] = set()
        unique: list[Article] = []
        for article in articles:
            if article.url and article.url not in seen:
                seen.add(article.url)
                unique.append(article)

        self._logger.info(f"PTT scan complete. Found {len(unique)} valid articles from {len(tags)} tags.")
        return unique[:limit]

    def save_social_media_data(self, articles: list[Article]) -> None:
        if not articles:
            self._logger.warning("No articles to save.")
            return

        archive_dir = self._config.project_root / "buzz_archive" / datetime.now().strftime("%Y-%m-%d")
        archive_dir.mkdir(parents=True, exist_ok=True)

        file_name = f"ptt_buzz_{datetime.now().strftime('%H%M%S')}.md"
        file_path = archive_dir / file_name

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("# Social Media Buzz (PTT)\n")
                f.write(f"**Generated at:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**Total Articles:** {len(articles)}\n\n---\n\n")

                for i, article in enumerate(articles, 1):
                    f.write(f"## [{i}] Stock {article.stock_id}: {article.title}\n")
                    f.write(f"- **Source:** {article.source.value}\n")
                    f.write(f"- **URL:** [Link]({article.url})\n\n")
                    f.write(f"**Content:**\n> {article.content[:500]}\n\n---\n\n")

            self._logger.trace(f"Saved PTT buzz archive to {file_path}")
        except Exception as e:
            self._logger.error(f"Failed to save PTT buzz archive: {e}")

    # ---------------------------------------------------------------------------- #
    #                               Core Scraping                                  #
    # ---------------------------------------------------------------------------- #

    async def _scrape_tag(self, tag: str, limit: int) -> list[Article]:
        cutoff = datetime.now().date() - timedelta(days=self._config.collect_rules.ptt_lookback_days)
        min_push = self._config.collect_rules.ptt_min_push_score
        universe = await self._load_universe()

        articles: list[Article] = []
        search_url: str | None = self.PTT_SEARCH_URL

        self._logger.debug(f"Scraping PTT tag: {tag} (lookback to {cutoff}, min push: {min_push})")

        async with httpx.AsyncClient(timeout=15.0, headers=self._headers, follow_redirects=True, verify=False) as client:
            while search_url and len(articles) < limit:
                try:
                    resp = await client.get(search_url, params={"q": tag} if "?" not in search_url else None)
                    resp.raise_for_status()
                except Exception as e:
                    self._logger.error(f"Failed to fetch PTT search page: {e}")
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                stop_pagination = False

                for div in soup.find_all("div", class_="r-ent"):
                    if len(articles) >= limit:
                        break

                    listing = self._parse_listing_row(div)
                    if not listing:
                        continue

                    # Date-based stop
                    post_date = self._parse_date(listing["date_str"])
                    if post_date < cutoff:
                        stop_pagination = True
                        break

                    # Push score pre-filter (Option 1: listing page)
                    if listing["push_score"] < min_push:
                        self._logger.trace(f"Skip (low push {listing['push_score']}): {listing['title']}")
                        continue

                    # Negative score = community rejected it
                    if listing["push_score"] < 0:
                        self._logger.trace(f"Skip (downvoted): {listing['title']}")
                        continue

                    # Fetch and process article (Option 2: body parsing)
                    article = await self._process_article(client, listing, universe)
                    if article:
                        articles.append(article)

                if stop_pagination:
                    self._logger.debug(f"Reached date cutoff ({cutoff}) for tag {tag}. Stopping pagination.")
                    break

                # Navigate to older results
                search_url = self._find_prev_page_url(soup)

        self._logger.debug(f"Tag {tag}: found {len(articles)} valid articles.")
        return articles

    async def _process_article(self, client: httpx.AsyncClient, listing: dict, universe: set[str]) -> Article | None:
        """Fetch article body, extract ticker, count engagement, clean content."""
        url = listing["url"]

        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
        except Exception as e:
            self._logger.debug(f"Failed to fetch article: {url} - {e}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        main_content = soup.find("div", id="main-content")
        if not main_content:
            return None

        # Count engagement BEFORE removing pushes (Option 2: body parsing)
        push_count, boo_count, comment_count = self._count_engagement(main_content)
        sentiment_ratio = push_count / (push_count + boo_count) if (push_count + boo_count) > 0 else 0.5

        # Extract ticker from full text (before cleaning)
        full_text = main_content.get_text(separator="\n", strip=True)
        ticker = self._extract_ticker(full_text)

        if not ticker or ticker not in universe:
            self._logger.trace(f"No valid TW ticker in: {listing['title']}")
            return None

        # Clean content (remove pushes, metadata, boilerplate)
        clean = self._clean_content(main_content)
        if not clean:
            return None

        # Prepend engagement stats so AI can see community reaction
        engagement_header = f"[社群反應: {push_count}推 {boo_count}噓 {comment_count}留言 | 正面比例: {sentiment_ratio:.0%}]"
        final_content = f"{engagement_header}\n{clean}"

        if len(final_content) > self.MAX_CONTENT_LENGTH:
            final_content = final_content[: self.MAX_CONTENT_LENGTH] + "..."

        self._logger.debug(
            f"Valid article: {ticker} | {listing['title']} (push:{push_count} boo:{boo_count} sentiment:{sentiment_ratio:.0%})"
        )

        return Article(
            id=uuid4(),
            stock_id=ticker,
            source=InformationSource.PTT_STOCK,
            title=listing["title"],
            content=final_content,
            url=url,
            content_type=ContentType.ANALYSIS,
            published_at=datetime.now(),
            fetched_at=datetime.now(),
        )

    # ---------------------------------------------------------------------------- #
    #                              Parsing Helpers                                 #
    # ---------------------------------------------------------------------------- #

    def _parse_listing_row(self, div) -> dict | None:
        """Parse a single row from PTT listing page."""
        title_a = div.find("a")
        if not title_a:
            return None

        title_text = title_a.get_text(strip=True)
        href = title_a.get("href", "")
        article_url = self.PTT_BASE_URL + str(href) if href else None

        # Push score
        nrec_div = div.find("div", class_="nrec")
        push_score = 0
        if nrec_div:
            push_score = self._parse_push_score(nrec_div.get_text(strip=True))

        # Date
        date_div = div.find("div", class_="date")
        date_str = date_div.get_text(strip=True) if date_div else ""

        if not article_url:
            return None

        return {
            "title": title_text,
            "url": article_url,
            "push_score": push_score,
            "date_str": date_str,
        }

    def _parse_push_score(self, text: str) -> int:
        """
        Parse PTT push score from listing page.
        +N  → positive N
        XN  → negative (community rejected)
        爆  → 100+ positive (viral)
        """
        text = text.strip()
        if not text:
            return 0
        if text == "爆":
            return 100
        if text.startswith("X"):
            return -1  # Downvoted — exact number doesn't matter, we skip it
        try:
            return int(text)
        except ValueError:
            return 0

    def _parse_date(self, date_str: str) -> date:
        """
        Parse PTT date format 'M/DD' into a date object.
        Handles year rollover (e.g., seeing '12/31' when current month is January).
        """
        date_str = date_str.strip()
        today = datetime.now().date()

        try:
            parts = date_str.split("/")
            if len(parts) != 2:
                return today

            month = int(parts[0])
            day = int(parts[1])
            year = today.year

            # Year rollover: if parsed month is ahead of current month, it's from last year
            if month > today.month:
                year -= 1

            return date(year, month, day)
        except (ValueError, IndexError):
            return today  # Fallback: treat unparseable dates as today (don't skip them)

    def _extract_ticker(self, content: str) -> str | None:
        """
        Extract 4-digit Taiwan stock ticker from article content.
        Priority 1: [標的] template → 股票代碼(股): 2330
        Priority 2: News convention → 台積電(2330)
        """
        # Pattern 1: Structured template field
        match = self._TICKER_TEMPLATE_RE.search(content)
        if match:
            return match.group(1)

        # Pattern 2: Parenthesized ticker in news text
        matches = self._TICKER_PARENS_RE.findall(content)
        if matches:
            # Return the first valid-looking ticker (starts with 1-9)
            for m in matches:
                if m[0] != "0":
                    return m

        return None

    def _count_engagement(self, main_content) -> tuple[int, int, int]:
        """Count 推/噓/→ from push divs. Returns (push, boo, comment)."""
        push_count = 0
        boo_count = 0
        comment_count = 0

        for push_div in main_content.find_all("div", class_="push"):
            tag_span = push_div.find("span", class_="push-tag")
            if not tag_span:
                continue
            tag_text = tag_span.get_text().strip()
            if tag_text == "推":
                push_count += 1
            elif tag_text == "噓":
                boo_count += 1
            elif tag_text == "→":
                comment_count += 1

        return push_count, boo_count, comment_count

    def _clean_content(self, main_content) -> str:
        """Remove pushes, metadata header, posting rules, and footer."""
        # Remove push comments
        for push in main_content.find_all("div", class_="push"):
            push.decompose()

        # Remove metadata spans (作者, 看板, 標題, 時間)
        for meta in main_content.find_all("div", class_="article-metaline"):
            meta.decompose()
        for meta in main_content.find_all("div", class_="article-metaline-right"):
            meta.decompose()

        raw_text = main_content.get_text(separator="\n", strip=True)

        # Remove posting rules block (between ------- lines)
        lines = raw_text.split("\n")
        cleaned_lines: list[str] = []
        in_rules_block = False

        for line in lines:
            stripped = line.strip()

            # Skip posting rules block
            if "發文提醒" in stripped or "按ctrl+y" in stripped.lower():
                in_rules_block = True
                continue
            if in_rules_block:
                if stripped.startswith("---") or stripped.startswith("──"):
                    in_rules_block = False
                continue

            # Skip separator lines
            if stripped.startswith("---") and len(stripped) > 5:
                continue

            # Skip footer lines
            if stripped.startswith("※"):
                continue

            # Skip empty lines in sequence
            if not stripped:
                if cleaned_lines and not cleaned_lines[-1]:
                    continue

            cleaned_lines.append(stripped)

        return "\n".join(cleaned_lines).strip()

    def _find_prev_page_url(self, soup) -> str | None:
        """Find the '上頁' (previous/older page) link for pagination."""
        paging = soup.find("div", class_="btn-group-paging")
        if not paging:
            return None

        for link in paging.find_all("a"):
            if "上頁" in link.get_text():
                href = link.get("href", "")
                if href:
                    return self.PTT_BASE_URL + href

        return None

    # ---------------------------------------------------------------------------- #
    #                            Universe Validation                               #
    # ---------------------------------------------------------------------------- #

    async def _load_universe(self) -> set[str]:
        """Load and cache the set of valid TWSE/TPEX stock IDs."""
        if self._universe_cache is None:
            self._logger.debug("Loading TWSE/TPEX universe for ticker validation...")
            stocks = await self._stock_provider.get_all()
            self._universe_cache = {s.stock_id for s in stocks}
            self._logger.debug(f"Universe loaded: {len(self._universe_cache)} stocks.")
        return self._universe_cache
