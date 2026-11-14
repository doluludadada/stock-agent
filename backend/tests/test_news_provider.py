import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from support.settings import shipped_config

from a_domain.model.market.article import Article
from a_domain.types.enums import InformationSource
from b_application.config.market_data_config import MarketHoursConfig
from c_infrastructure.feed.news import cnyes_news_provider, yahoo_tw_news_provider
from c_infrastructure.feed.news_provider import NewsProvider
from c_infrastructure.system.market_clock import TaiwanMarketClock

SOURCES = shipped_config().sources


class SilentLogger:
    def __getattr__(self, name: str):
        return lambda message: None


def article(title: str, url: str | None) -> Article:
    published_at = datetime(2026, 10, 30, tzinfo=UTC)
    return Article(
        stock_id="2330",
        source=InformationSource.NEWS_MEDIA,
        title=title,
        content=title,
        url=url,
        published_at=published_at,
        fetched_at=published_at,
    )


class ScriptedSource:
    def __init__(self, articles: list[Article] | Exception) -> None:
        self._articles = articles
        self.limits: list[int] = []

    async def fetch_news(self, stock_id: str, limit: int) -> list[Article]:
        self.limits.append(limit)

        if isinstance(self._articles, Exception):
            raise self._articles

        return self._articles[:limit]


def provider(*sources: ScriptedSource) -> NewsProvider:
    return NewsProvider(sources, shipped_config(), SilentLogger(), TaiwanMarketClock(MarketHoursConfig()))


@pytest.mark.asyncio
async def test_a_later_site_is_asked_only_for_what_the_earlier_ones_did_not_find() -> None:
    first = ScriptedSource([article("a", "https://a"), article("b", "https://b")])
    second = ScriptedSource([article("b again", "https://b"), article("c", None), article("d", "https://d")])
    unused = ScriptedSource([article("never", "https://never")])

    news = await provider(first, second, unused).fetch_news("2330", limit=4)

    assert [item.title for item in news] == ["a", "b", "c"]
    assert (first.limits, second.limits, unused.limits) == ([4], [2], [])


@pytest.mark.asyncio
async def test_a_failing_site_is_skipped() -> None:
    working = ScriptedSource([article("a", "https://a")])

    news = await provider(ScriptedSource(RuntimeError("cnyes is down")), working).fetch_news("2330", limit=3)

    assert [item.title for item in news] == ["a"]
    assert working.limits == [3]


def test_a_yahoo_news_page_lists_each_headline_once_with_its_full_url() -> None:
    page = """
    <a href="/news/tsmc-1.html">TSMC raises its outlook</a>
    <a href="/news/tsmc-1.html">TSMC raises its outlook</a>
    <a href="https://tw.news.yahoo.com/news/tsmc-2.html">TSMC capex grows</a>
    <a href="/news/short.html">Up</a>
    <a href="/quote/2330">Quote page</a>
    """

    articles = yahoo_tw_news_provider.parse_listing("2330", page, SOURCES.news)

    assert [(item.title, item.url) for item in articles] == [
        ("TSMC raises its outlook", f"{SOURCES.news.yahoo_base_url}/news/tsmc-1.html"),
        ("TSMC capex grows", "https://tw.news.yahoo.com/news/tsmc-2.html"),
    ]


@pytest.mark.asyncio
async def test_a_yahoo_article_without_caas_body_keeps_only_paragraphs_longer_than_20_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = f"<p>{'a' * 20}</p><p>{'b' * 21}</p>"
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=page))),
    )

    async with httpx.AsyncClient() as client:
        body = await yahoo_tw_news_provider.fetch_article_body(
            "https://tw.stock.yahoo.com/news/a.html", client, SOURCES.news, SilentLogger()
        )

    assert body == "b" * 21


def test_a_cnyes_item_without_a_time_is_undated_and_the_audit_file_gives_it_no_publication_time(tmp_path: Path) -> None:
    listing = {"items": {"data": [{"newsId": 1, "title": "timed", "publishAt": 1761790200}, {"newsId": 2, "title": "untimed"}]}}
    clock = TaiwanMarketClock(MarketHoursConfig())

    articles = cnyes_news_provider.parse_listing("2330", json.dumps(listing), SOURCES.news.cnyes_article_url, SilentLogger())
    NewsProvider((), shipped_config(tmp_path), SilentLogger(), clock).save_as_md_file("2330", articles)

    [saved] = (tmp_path / "news_archive").glob("*/2330_*.md")
    timed, untimed = saved.read_text(encoding="utf-8").split("## [2] untimed")
    assert [(article.title, article.publication_known) for article in articles] == [("timed", True), ("untimed", False)]
    assert articles[0].published_at == datetime(2025, 10, 30, 2, 10, tzinfo=UTC)
    assert "**Published:** 2025-10-30 10:10" in timed and "Published" not in untimed
