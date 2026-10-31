from datetime import UTC, datetime

import httpx
import pytest
from support.settings import shipped_config

from a_domain.model.market.article import Article
from a_domain.types.enums import InformationSource
from b_application.config.sources_config import SourcesConfig
from c_infrastructure.feed.news.yahoo_tw_news_provider import YahooTwNewsProvider
from c_infrastructure.feed.news_provider import NewsProvider

SOURCES = SourcesConfig.from_appsetting()


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
    return NewsProvider(sources, shipped_config(), SilentLogger())


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

    articles = YahooTwNewsProvider(SOURCES.news, SilentLogger()).parse_listing("2330", page)

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

    body = await YahooTwNewsProvider(SOURCES.news, SilentLogger()).fetch_article_body("https://tw.stock.yahoo.com/news/a.html")

    assert body == "b" * 21
