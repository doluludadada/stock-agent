import re
from datetime import date, datetime, timedelta
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup, Tag

from a_domain.model.market.article import Article
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import ContentType, InformationSource
from b_application.schemas.config import AppConfig


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
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": "over18=1",
    }
    RE_TICKER_TEMPLATE = re.compile(r"股票代碼[^:：]*[:：]\s*(\d{4})")
    RE_TICKER_PARENS = re.compile(r"[（(](\d{4})[)）]")
    RE_TICKER_TITLE = re.compile(r"(\d{4})")

    def __init__(
        self,
        config: AppConfig,
        logger: ILoggingProvider,
        stock: IStockProvider,
    ):
        self._config = config
        self._log = logger
        self._stock = stock
        self._universe: set[str] | None = None

    # ── public ────────────────────────────────────────────────────── #

    async def get_trending_stocks(self, limit: int) -> list[Article]:
        self._log.info("Scanning PTT Stock board for trending posts...")
        universe = await self._ensure_universe()
        rules = self._config.collect_rules
        cutoff = datetime.now().date() - timedelta(days=rules.ptt_lookback_days)

        collected: list[Article] = []
        async with httpx.AsyncClient(
            timeout=15.0,
            headers=self.HEADERS,
            follow_redirects=True,
            verify=False,
        ) as http:
            for tag in rules.ptt_tags:
                articles = await self._scrape_tag(
                    http,
                    tag,
                    universe,
                    cutoff,
                    rules.ptt_min_push_score,
                    limit,
                )
                collected.extend(articles)

        result = _dedupe(collected)[:limit]
        self._log.info(f"PTT scan complete. {len(result)} unique articles.")
        return result

    def save_social_media_data(self, articles: list[Article]) -> None:
        if not articles:
            return
        now = datetime.now()
        out = self._config.project_root / "buzz_archive" / now.strftime("%Y-%m-%d")
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"ptt_buzz_{now.strftime('%H%M%S')}.md"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# PTT Buzz — {now:%Y-%m-%d %H:%M}\n\n")
                for i, a in enumerate(articles, 1):
                    f.write(f"## [{i}] {a.stock_id}: {a.title}\n")
                    f.write(f"- {a.source.value} | {a.url}\n\n")
                    f.write(f"> {a.content[:500]}\n\n---\n\n")
            self._log.trace(f"Buzz archive saved → {path}")
        except Exception as e:
            self._log.error(f"Buzz archive write failed: {e}")

    # --------------------------------- scraping --------------------------------- #

    async def _scrape_tag(
        self,
        http: httpx.AsyncClient,
        tag: str,
        universe: set[str],
        cutoff: date,
        min_push: int,
        budget: int,
    ) -> list[Article]:
        self._log.debug(f"[{tag}] scraping (cutoff={cutoff}, min_push={min_push}, budget={budget})")

        articles: list[Article] = []
        next_url: str | None = None

        for page_num in range(1, self.MAX_PAGES + 1):
            soup = await self._get_page(http, tag, next_url)
            if soup is None:
                break

            divs = soup.find_all("div", class_="r-ent")
            if not divs:
                break

            reached_cutoff = False
            for div in divs:
                listing = _parse_listing(div)
                if listing is None:
                    continue

                if listing["date"] < cutoff:
                    reached_cutoff = True
                    continue

                if listing["push"] < min_push:
                    continue

                article = await self._build_article(http, listing, universe)
                if article:
                    articles.append(article)
                    if len(articles) >= budget:
                        break

            self._log.debug(f"[{tag}] page {page_num}: {len(divs)} rows → {len(articles)}/{budget} collected")

            if reached_cutoff or len(articles) >= budget:
                break

            next_url = _prev_page_url(soup)
            if next_url is None:
                break

        self._log.debug(f"[{tag}] done — {len(articles)} articles")
        return articles

    async def _get_page(
        self,
        http: httpx.AsyncClient,
        tag: str,
        url: str | None,
    ) -> BeautifulSoup | None:
        try:
            if url is None:
                r = await http.get(self.SEARCH_URL, params={"q": tag})
            else:
                r = await http.get(url)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            self._log.error(f"Page fetch failed: {type(e).__name__}: {e}")
            return None

    async def _build_article(
        self,
        http: httpx.AsyncClient,
        listing: dict,
        universe: set[str],
    ) -> Article | None:
        body_tag = await self._fetch_body(http, listing["url"])
        if body_tag is None:
            return None

        text = body_tag.get_text(separator="\n", strip=True)
        ticker = _extract_ticker(text, listing["title"])
        if ticker is None or ticker not in universe:
            return None

        push, boo, arrows = _count_engagement(body_tag)
        clean = _extract_clean_text(body_tag)
        if not clean:
            return None

        ratio = push / (push + boo) if (push + boo) > 0 else 0.5
        body = f"[{push}推 {boo}噓 {arrows}→ | 正面{ratio:.0%}]\n{clean}"
        if len(body) > self.MAX_BODY_LEN:
            body = body[: self.MAX_BODY_LEN] + "…"

        self._log.debug(f"✓ {ticker} | {listing['title']} ({push}推 {boo}噓 {ratio:.0%})")

        return Article(
            id=uuid4(),
            stock_id=ticker,
            source=InformationSource.PTT_STOCK,
            title=listing["title"],
            content=body,
            url=listing["url"],
            content_type=ContentType.ANALYSIS,
            published_at=datetime.now(),
            fetched_at=datetime.now(),
        )

    async def _fetch_body(self, http: httpx.AsyncClient, url: str) -> Tag | None:
        try:
            r = await http.get(url)
            if r.status_code != 200:
                return None
            tag = BeautifulSoup(r.text, "html.parser").find("div", id="main-content")
            return tag if isinstance(tag, Tag) else None
        except Exception:
            return None

    async def _ensure_universe(self) -> set[str]:
        if self._universe is None:
            self._log.debug("Loading TWSE/TPEX universe…")
            stocks = await self._stock.get_all()
            self._universe = {s.stock_id for s in stocks}
            self._log.debug(f"Universe: {len(self._universe)} stocks")
        return self._universe


# ── pure helpers ─────────────────────────────────────────────────── #


def _parse_listing(div: Tag) -> dict | None:
    anchor = div.find("a")
    if anchor is None:
        return None
    href = anchor.get("href", "")
    if not href or not isinstance(href, str):
        return None
    return {
        "title": anchor.get_text(strip=True),
        "url": PttProvider.BASE_URL + href,
        "push": _parse_push(div.find("div", class_="nrec")),
        "date": _parse_date(div.find("div", class_="date")),
    }


def _parse_push(nrec: Tag | None) -> int:
    if nrec is None:
        return 0
    t = nrec.get_text(strip=True)
    if not t:
        return 0
    if t == "爆":
        return 100
    if t == "XX":
        return -100
    if t.startswith("X") and len(t) == 2 and t[1].isdigit():
        return -int(t[1]) * 10
    try:
        return int(t)
    except ValueError:
        return 0


def _parse_date(date_div: Tag | None) -> date:
    today = datetime.now().date()
    if date_div is None:
        return today
    parts = date_div.get_text(strip=True).split("/")
    if len(parts) != 2:
        return today
    try:
        m, d = int(parts[0]), int(parts[1])
        y = today.year if m <= today.month else today.year - 1
        return date(y, m, d)
    except (ValueError, IndexError):
        return today


def _extract_ticker(body: str, title: str) -> str | None:
    m = PttProvider.RE_TICKER_TEMPLATE.search(body)
    if m:
        return m.group(1)
    for hit in PttProvider.RE_TICKER_PARENS.findall(body):
        if not hit.startswith("0"):
            return hit
    m = PttProvider.RE_TICKER_TITLE.search(title)
    return m.group(1) if m else None


def _count_engagement(main: Tag) -> tuple[int, int, int]:
    push = boo = arrow = 0
    for div in main.find_all("div", class_="push"):
        span = div.find("span", class_="push-tag")
        if span is None:
            continue
        tag = span.get_text().strip()
        if tag == "推":
            push += 1
        elif tag == "噓":
            boo += 1
        elif tag == "→":
            arrow += 1
    return push, boo, arrow


def _extract_clean_text(main: Tag) -> str:
    for cls in ("push", "article-metaline", "article-metaline-right"):
        for el in main.find_all("div", class_=cls):
            el.decompose()

    lines: list[str] = []
    for raw in main.get_text(separator="\n", strip=True).split("\n"):
        s = raw.strip()
        if not s:
            if lines and lines[-1]:
                lines.append("")
            continue
        if s.startswith("※") or s.startswith("---") and len(s) > 5:
            continue
        if "發文提醒" in s or "ctrl+y" in s.lower():
            continue
        lines.append(s)
    return "\n".join(lines).strip()


def _prev_page_url(soup: BeautifulSoup) -> str | None:
    paging = soup.find("div", class_="btn-group-paging")
    if paging is None:
        return None
    for a in paging.find_all("a"):
        if "上頁" in a.get_text():
            href = a.get("href", "")
            if isinstance(href, str) and href:
                return PttProvider.BASE_URL + href
    return None


def _dedupe(articles: list[Article]) -> list[Article]:
    seen: set[str] = set()
    out: list[Article] = []
    for a in articles:
        key = a.url or a.title
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out
