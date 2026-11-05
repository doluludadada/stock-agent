from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from support.settings import shipped_config
from trading_stack import run_stats

from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.post_listing import PostListing
from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.types.enums import InformationSource, Workflow
from b_application.config.app_config import AppConfig
from b_application.config.market_data_config import MarketDataConfig, MarketHoursConfig
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from c_infrastructure.feed.ptt_provider import PttProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.system.market_clock import TaiwanMarketClock

SOURCES = shipped_config().sources


class SilentLogger:
    def __getattr__(self, name: str):
        return lambda message: None


class FakeSocialMediaProvider:
    def __init__(self, articles: list[Article]) -> None:
        self._articles = articles

    async def fetch_social_articles(self, limit: int) -> list[Article]:
        return list(self._articles)

    def save_social_media_data(self, articles: list[Article]) -> None:
        return None


class FakeStockList:
    async def get_all(self) -> list[Stock]:
        return [Stock(stock_id="2330")]


def make_post(stock_id: str, engagement: int = 0) -> Article:
    return Article(
        stock_id=stock_id,
        source=InformationSource.PTT_STOCK,
        title=f"[標的] {stock_id}",
        content="discussion",
        published_at=datetime(2026, 10, 30, tzinfo=UTC),
        fetched_at=datetime(2026, 10, 30, tzinfo=UTC),
        engagement=engagement,
    )


def make_config(min_mentions: int, min_engagement: int) -> AppConfig:
    shipped = shipped_config()
    thresholds = {"buzz_min_mentions": min_mentions, "buzz_min_engagement": min_engagement}
    return shipped.model_copy(update={"collect_rules": shipped.collect_rules.model_copy(update=thresholds)})


async def make_stock_provider(monkeypatch: pytest.MonkeyPatch, stock_ids: list[str]) -> TaiwanStockProvider:
    provider = TaiwanStockProvider(
        exchange=SOURCES.exchange,
        market_clock=TaiwanMarketClock(MarketHoursConfig()),
        market_data=MarketDataConfig(),
        logger=SilentLogger(),
    )

    async def fetch_listings() -> tuple[list[Stock], dict[str, Ohlcv]]:
        return [Stock(stock_id=stock_id) for stock_id in stock_ids], {}

    monkeypatch.setattr(provider, "fetch_listings", fetch_listings)
    return provider


async def scan(articles: list[Article], stock_provider: TaiwanStockProvider, config: AppConfig) -> tuple[list[Stock], SystemStats]:
    scanner = BuzzScanner(
        social_media_provider=FakeSocialMediaProvider(articles), stock_provider=stock_provider, logger=SilentLogger(), config=config
    )
    stats = run_stats(Workflow.BUZZ_SCAN)
    return await scanner.execute({}, stats), stats


@pytest.mark.asyncio
async def test_buzz_articles_do_not_leak_into_later_workflows_in_the_same_session(monkeypatch: pytest.MonkeyPatch) -> None:
    stock_provider = await make_stock_provider(monkeypatch, ["2330"])
    config = make_config(min_mentions=1, min_engagement=1000)

    first_scan, _ = await scan([make_post("2330")], stock_provider, config)
    second_scan, _ = await scan([make_post("2330")], stock_provider, config)
    later_lookup = await stock_provider.get_by_id("2330")

    assert len(first_scan[0].articles) == 1
    assert len(second_scan[0].articles) == 1
    assert later_lookup is not None
    assert later_lookup.articles == []


@pytest.mark.asyncio
async def test_a_stock_qualifies_by_mention_count_or_by_engagement(monkeypatch: pytest.MonkeyPatch) -> None:
    stock_provider = await make_stock_provider(monkeypatch, ["1111", "2222", "3333"])
    config = make_config(min_mentions=20, min_engagement=100)
    many_mentions = [make_post("1111") for _ in range(20)]
    one_engaged_post = [make_post("2222", engagement=100)]
    below_both_thresholds = [make_post("3333", engagement=5) for _ in range(19)]

    buzz_stocks, stats = await scan([*many_mentions, *one_engaged_post, *below_both_thresholds], stock_provider, config)

    assert [stock.stock_id for stock in buzz_stocks] == ["1111", "2222"]
    assert [len(stock.articles) for stock in buzz_stocks] == [20, 1]
    assert stats.buzz_scanned == 3
    assert stats.buzz_qualified == 2


@pytest.mark.asyncio
async def test_engagement_one_below_the_threshold_does_not_qualify(monkeypatch: pytest.MonkeyPatch) -> None:
    stock_provider = await make_stock_provider(monkeypatch, ["2222"])
    config = make_config(min_mentions=20, min_engagement=100)

    buzz_stocks, stats = await scan([make_post("2222", engagement=60), make_post("2222", engagement=39)], stock_provider, config)

    assert buzz_stocks == []
    assert stats.buzz_scanned == 1
    assert stats.buzz_qualified == 0


def test_ptt_post_engagement_counts_every_push_boo_and_arrow() -> None:
    html = """
    <div id="main-content">
      <div class="article-metaline">作者 tester</div>
      股票代碼：2330
      台積電法說會後的看法，內文足夠長。
      <div class="push"><span class="push-tag">推 </span><span>u1</span></div>
      <div class="push"><span class="push-tag">推 </span><span>u2</span></div>
      <div class="push"><span class="push-tag">噓 </span><span>u3</span></div>
      <div class="push"><span class="push-tag">→ </span><span>u4</span></div>
    </div>
    """
    ptt = PttProvider(config=shipped_config(), logger=SilentLogger(), stock_provider=FakeStockList())
    listing = PostListing(title="[標的] 2330 台積電 多", url="https://www.ptt.cc/bbs/Stock/M.1.html", posted_on=date(2026, 10, 30))

    article = ptt.parse_article(html, listing, stock_ids={"2330"})

    assert article is not None
    assert article.stock_id == "2330"
    assert article.engagement == 4


class PttBoard:
    """Stands in for httpx.AsyncClient on the PTT board: two search pages, the second one reaching past the cutoff."""

    requested: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        PttBoard.requested = []

    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        PttBoard.requested.append(url)
        request = httpx.Request("GET", url)
        today = datetime.now().date()

        def row(post: str, days_ago: int) -> str:
            posted = today - timedelta(days=days_ago)
            link = f'<a href="/bbs/Stock/{post}.html">[標的] {post}</a>'
            return f'<div class="r-ent">{link}<div class="date">{posted.month}/{posted.day:02d}</div></div>'

        if url.endswith("/search"):
            paging = '<div class="btn-group-paging"><a href="/bbs/Stock/search?page=2">‹ 上頁</a></div>'
            return httpx.Response(200, text=paging + row("M.1", 1) + row("M.2", 2), request=request)

        if "page=2" in url:
            return httpx.Response(200, text=row("M.3", 3) + row("M.4", 30), request=request)

        return httpx.Response(200, text=f'<div id="main-content">股票代碼：2330\n{url} 的內容</div>', request=request)


@pytest.mark.asyncio
async def test_ptt_pages_back_through_the_search_until_a_post_is_older_than_the_lookback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", PttBoard)
    shipped = shipped_config()
    collect_rules = shipped.collect_rules.model_copy(update={"ptt_tags": ["[標的]"], "ptt_lookback_days": 14})
    config = shipped.model_copy(update={"collect_rules": collect_rules})
    ptt = PttProvider(config=config, logger=SilentLogger(), stock_provider=FakeStockList())

    articles = await ptt.fetch_social_articles(limit=10)

    assert [article.url for article in articles] == [f"{SOURCES.ptt.base_url}/bbs/Stock/M.{post}.html" for post in (1, 2, 3)]
    assert f"{SOURCES.ptt.base_url}/bbs/Stock/M.4.html" not in PttBoard.requested


def test_a_ptt_article_is_cut_to_3000_characters() -> None:
    ptt = PttProvider(config=shipped_config(), logger=SilentLogger(), stock_provider=FakeStockList())
    listing = PostListing(title="[標的] 2330 台積電 多", url="https://www.ptt.cc/bbs/Stock/M.1.html", posted_on=date(2026, 10, 30))

    article = ptt.parse_article(f'<div id="main-content">股票代碼：2330\n{"長" * 4000}</div>', listing, stock_ids={"2330"})

    assert article is not None
    assert len(article.content) == 3000


class EndlessPttBoard:
    """Stands in for httpx.AsyncClient on a PTT search that always has an older page with a fresh post on it."""

    search_pages: int = 0

    def __init__(self, *args, **kwargs) -> None:
        EndlessPttBoard.search_pages = 0

    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        request = httpx.Request("GET", url)

        if "/M." in url:
            return httpx.Response(200, text='<div id="main-content">no ticker here</div>', request=request)

        EndlessPttBoard.search_pages += 1
        today = datetime.now().date()
        paging = f'<div class="btn-group-paging"><a href="/bbs/Stock/search?page={EndlessPttBoard.search_pages + 1}">‹ 上頁</a></div>'
        post = f'<div class="r-ent"><a href="/bbs/Stock/M.{EndlessPttBoard.search_pages}.html">[閒聊] chat</a>'
        return httpx.Response(200, text=f'{paging}{post}<div class="date">{today.month}/{today.day:02d}</div></div>', request=request)


@pytest.mark.asyncio
async def test_ptt_reads_at_most_30_search_pages_for_one_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", EndlessPttBoard)
    ptt = PttProvider(config=shipped_config(), logger=SilentLogger(), stock_provider=FakeStockList())

    articles = await ptt.fetch_tag_articles("[閒聊]", {"2330"}, datetime.now().date() - timedelta(days=14), limit=10)

    assert articles == []
    assert EndlessPttBoard.search_pages == 30


def test_the_buzz_archive_quotes_the_first_500_characters_of_each_post(tmp_path: Path) -> None:
    ptt = PttProvider(config=shipped_config(tmp_path), logger=SilentLogger(), stock_provider=FakeStockList())
    post = replace(make_post("2330"), content="a" * 500 + "b" * 100)

    ptt.save_social_media_data([post])

    archive = next(tmp_path.rglob("ptt_buzz_*.md")).read_text(encoding="utf-8")
    assert f"> {'a' * 500}\n" in archive
    assert "a" * 500 + "b" not in archive


@pytest.mark.parametrize(
    ("title", "stock_id"),
    [("[標的] 2330 台積電 多", "2330"), ("[新聞] 台積電 2330A", "2330"), ("[標的] 123 多", None), ("[閒聊] 台積電", None)],
)
def test_a_post_whose_body_names_no_stock_takes_its_stock_id_from_the_title(title: str, stock_id: str | None) -> None:
    ptt = PttProvider(config=shipped_config(), logger=SilentLogger(), stock_provider=FakeStockList())

    assert ptt.extract_stock_id("A post with no ticker line.", title) == stock_id
