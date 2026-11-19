"""
The world outside Taiwan's exchanges: the world news feeds' items kept in the article store, the world indicators'
readings, and the day's world brief, which the site's own writing writes once per Taipei day from held items alone.
"""

import asyncio
import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import override

import httpx
import pytest
from support.harness import MARKET_OPEN, MEMBER, MEMBER_PASSWORD, CliHarness, build_harness, harness_config
from support.web import serve
from test_settings_form import PROJECT, project_with, repository_texts
from test_stock_brief import INSTRUCTIONS, BriefAi
from trading_stack import MovableClock

from a_domain.model.market.article import Article
from a_domain.model.market.stock import Stock
from a_domain.model.market.world_indicator import IndicatorReading
from a_domain.rules.ai.world_brief import named_stocks
from a_domain.types.enums import (
    Audience,
    BriefSourceKind,
    BriefStatus,
    ContentType,
    Feature,
    FeatureVisibility,
    InformationSource,
    MarketScope,
    MarketType,
    SettingsFile,
    TableFormat,
    WorldIndicator,
)
from a_domain.types.errors import AiAllowanceSpentError
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import load_settings, settings_notices
from b_application.config.sources_config import WorldIndicatorFeed, WorldNewsFeed, WorldSources
from b_application.schemas.collect import WorldUpdate
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.stock_brief_dto import WorldBriefDTO
from c_infrastructure.database.repositories.article_store import SqlArticleStore
from c_infrastructure.database.repositories.stock_brief_repository import SqlStockBriefRepository
from c_infrastructure.database.repositories.world_indicator_repository import SqlWorldIndicatorRepository
from c_infrastructure.feed.world_feed import WorldFeed
from c_infrastructure.request_pace import RequestPace
from d_presentation.dependencies import compose_runtime, create_world_feed

pytestmark = pytest.mark.asyncio

WORLD = MarketScope.WORLD.value
MORNING = datetime.combine(MARKET_OPEN.date(), time(7, 45), MARKET_OPEN.tzinfo)
TODAY = MORNING.date()
CNA_WORLD = "https://feeds.example/cna/world"
CNA_FINANCE = "https://feeds.example/cna/finance"
BBC_BUSINESS = "https://feeds.example/bbc/business"
FED = "https://feeds.example/fed/monetary"
RATES = "https://tables.example/rates"
YIELDS = "https://tables.example/yields/{year}"
SOURCES = WorldSources(
    news_feeds=[
        WorldNewsFeed(source=InformationSource.CNA, url=CNA_WORLD),
        WorldNewsFeed(source=InformationSource.CNA, url=CNA_FINANCE),
        WorldNewsFeed(source=InformationSource.BBC, url=BBC_BUSINESS),
        WorldNewsFeed(source=InformationSource.FEDERAL_RESERVE, url=FED),
    ],
    indicator_feeds=[
        WorldIndicatorFeed(
            url=RATES, format=TableFormat.JSON, date_field="Date", date_format="%Y%m%d", fields={"USD/NTD": WorldIndicator.USD_TWD}
        ),
        WorldIndicatorFeed(
            url=YIELDS,
            format=TableFormat.CSV,
            date_field="Date",
            date_format="%m/%d/%Y",
            fields={"10 Yr": WorldIndicator.US_10Y_YIELD},
        ),
    ],
    request_pause_seconds=0,
)


def rss(*items: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>feed</title>{"".join(items)}</channel></rss>'


def item(title: str, link: str, summary: str = "", published: str | None = "Sun, 18 Oct 2026 22:30:00 GMT") -> str:
    stamp = f"<pubDate>{published}</pubDate>" if published else ""
    return f"<item><title>{title}</title><link>{link}</link><description>{summary}</description>{stamp}</item>"


CHIPS = item("美擴大晶片出口管制 台積電稱影響有限", "https://cna.example/1", "<![CDATA[（中央社）美國商務部宣布<b>擴大</b>管制。]]>")
RATE_CUT = item("Fed cuts rates by a quarter point", "https://bbc.example/2", "The Federal Reserve lowered its key rate.")
STATEMENT = item("Federal Reserve issues FOMC statement", "https://fed.example/3", "Federal Reserve issues FOMC statement")


class Web:
    """The hosts behind the world feeds: what each address answers, and every address that was asked."""

    def __init__(self, pages: dict[str, str | int | Exception | httpx.Response]) -> None:
        self.pages = pages
        self.asked: list[str] = []

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(str(request.url))
        page = self.pages.get(str(request.url), 404)

        if isinstance(page, Exception):
            raise page

        if isinstance(page, httpx.Response):
            return page

        return httpx.Response(page) if isinstance(page, int) else httpx.Response(200, text=page)


def feed_over(monkeypatch: pytest.MonkeyPatch, web: Web, harness: CliHarness, sources: WorldSources = SOURCES) -> WorldFeed:
    """The real adapter of every feed in `sources`, over `web` in place of the network."""
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(web.answer), **kwargs))
    return WorldFeed(sources, sources.news_feeds, sources.indicator_feeds, 400, harness.clock, harness.logger, RequestPace())


# ------------------------------------------------ the feeds ------------------------------------------------ #


async def test_a_feeds_items_are_read_as_plain_text_with_their_time_and_address(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = build_harness(now=MORNING)
    web = Web({CNA_WORLD: rss(CHIPS), BBC_BUSINESS: rss(RATE_CUT), FED: rss(STATEMENT)})

    items = await feed_over(monkeypatch, web, harness).fetch_news()

    chips, rate_cut, statement = items
    assert (chips.stock_id, chips.source, chips.content_type) == (WORLD, InformationSource.CNA, ContentType.NEWS)
    assert (chips.title, chips.content) == ("美擴大晶片出口管制 台積電稱影響有限", "（中央社）美國商務部宣布 擴大 管制。")
    assert (chips.url, chips.published_at) == ("https://cna.example/1", datetime.fromisoformat("2026-10-18T22:30:00+00:00"))
    assert (rate_cut.source, rate_cut.content) == (InformationSource.BBC, "The Federal Reserve lowered its key rate.")
    assert (statement.source, statement.content) == (InformationSource.FEDERAL_RESERVE, ""), "a summary that repeats the title is none"
    assert chips.open_text == chips.content, "a feed's own summary may be shown and may reach a brief's prompt"


async def test_markup_in_a_title_is_text_and_an_item_without_a_title_or_a_web_address_is_left_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(now=MORNING)
    marked = item("&lt;script&gt;alert(1)&lt;/script&gt;Oil &amp; gas &lt;i&gt;rise&lt;/i&gt;", "https://bbc.example/9")
    unsafe = item("A link that is no web address", "javascript:alert(1)")
    untitled = item("", "https://bbc.example/10")
    undated = item("No time given", "https://bbc.example/11", published=None)
    web = Web({BBC_BUSINESS: rss(marked, unsafe, untitled, undated)})

    items = await feed_over(monkeypatch, web, harness).fetch_news()

    assert [(article.title, article.url) for article in items] == [
        ("Oil & gas rise", "https://bbc.example/9"),
        ("No time given", "https://bbc.example/11"),
    ]
    assert [article.publication_known for article in items] == [True, False]


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param(503, id="the host refuses"),
        pytest.param(httpx.ConnectError("no route"), id="the host is down"),
        pytest.param("<rss><channel><item><title>cut off", id="malformed XML"),
        pytest.param("<html><body>Please verify your browser</body>", id="a page that is no feed"),
        pytest.param(
            '<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaa">]>' + rss(item("&a;", "https://cna.example/7")),
            id="a feed that declares entities",
        ),
        pytest.param(rss(item("Too large", "https://cna.example/8", "x" * 3000)), id="more than the most bytes"),
        pytest.param(httpx.Response(302, headers={"Location": BBC_BUSINESS}), id="the host redirects"),
    ],
)
async def test_a_feed_that_cannot_be_read_is_logged_and_the_others_are_still_answered(
    monkeypatch: pytest.MonkeyPatch, broken: str | int | Exception | httpx.Response
) -> None:
    harness = build_harness(now=MORNING)
    web = Web({CNA_WORLD: broken, BBC_BUSINESS: rss(RATE_CUT)})
    sources = SOURCES.model_copy(update={"max_bytes": 2000})

    items = await feed_over(monkeypatch, web, harness, sources).fetch_news()

    assert [article.url for article in items] == ["https://bbc.example/2"]
    assert web.asked == [CNA_WORLD, CNA_FINANCE, BBC_BUSINESS, FED]
    assert any("World feed of CNA was not read" in line for _, line in harness.logger.records)


async def test_a_feed_in_utf_16_is_read_and_one_that_declares_an_entity_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = build_harness(now=MORNING)
    channel = "<rss><channel>" + item("&a;聯準會降息", "https://bbc.example/12") + "</channel></rss>"
    declared = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE rss [<!ENTITY a "aaaa">]>' + channel
    plain = '<?xml version="1.0" encoding="UTF-16"?>' + channel.replace("&a;", "")
    web = Web(
        {
            CNA_WORLD: httpx.Response(200, content=declared.encode("utf-16")),
            BBC_BUSINESS: httpx.Response(200, content=plain.encode("utf-16")),
        }
    )

    items = await feed_over(monkeypatch, web, harness).fetch_news()

    assert [article.title for article in items] == ["聯準會降息"]
    assert any(
        "World feed of CNA was not read: ValueError: the feed declares a document type" in line for _, line in harness.logger.records
    )


async def test_a_response_past_the_most_bytes_is_given_up_before_its_end(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = build_harness(now=MORNING)
    served: list[int] = []

    async def endless():
        for _ in range(1000):
            served.append(1000)
            yield b"x" * 1000

    web = Web({CNA_WORLD: httpx.Response(200, content=endless()), BBC_BUSINESS: rss(RATE_CUT)})
    sources = SOURCES.model_copy(update={"max_bytes": 5000})

    items = await feed_over(monkeypatch, web, harness, sources).fetch_news()

    assert [article.url for article in items] == ["https://bbc.example/2"]
    assert sum(served) < 1_000_000, "the body is not read to its end"
    assert any("World feed of CNA was not read: ValueError" in line for _, line in harness.logger.records)


async def test_an_item_dated_later_than_its_read_is_counted_in_one_debug_line_per_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = build_harness(now=MORNING)
    later = "Sun, 18 Oct 2099 22:30:00 GMT"
    ahead = [
        item("Tomorrow's news", "https://bbc.example/13", published=later),
        item("And more", "https://bbc.example/14", published=later),
    ]
    web = Web({BBC_BUSINESS: rss(RATE_CUT, *ahead), FED: rss(STATEMENT)})

    items = await feed_over(monkeypatch, web, harness).fetch_news()

    assert [article.publication_known for article in items] == [True, False, False, True]
    assert [line for level, line in harness.logger.records if level == "debug" and "dated later" in line] == [
        "World feed of BBC: 2 items are dated later than their read."
    ]


async def test_requests_leave_on_the_pace_the_wiring_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = build_harness(now=MORNING)
    waits: list[float] = []

    class CountedPace(RequestPace):
        @override
        async def wait(self, interval_seconds: float) -> None:
            waits.append(interval_seconds)

    web = Web({FED: rss(STATEMENT)})
    sources = SOURCES.model_copy(update={"request_pause_seconds": 7})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(web.answer), **kwargs))
    feed = WorldFeed(sources, sources.news_feeds, sources.indicator_feeds, 400, harness.clock, harness.logger, CountedPace())

    await feed.fetch_news()
    await feed.fetch_indicators()

    assert waits == [7] * len(web.asked) and len(web.asked) == 6


async def test_an_item_two_feeds_list_is_answered_once(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = build_harness(now=MORNING)
    web = Web({CNA_WORLD: rss(CHIPS), CNA_FINANCE: rss(CHIPS, item("台股收盤", "https://cna.example/4"))})

    items = await feed_over(monkeypatch, web, harness).fetch_news()

    assert [article.url for article in items] == ["https://cna.example/1", "https://cna.example/4"]


async def test_the_indicators_tables_are_read_as_dated_readings_and_a_table_that_cannot_be_read_is_left_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(now=MORNING)
    rates = json.dumps(
        [
            {"Date": "20260901", "USD/NTD": "31.000"},
            {"Date": "20261015", "USD/NTD": "32.800", "USD/JPY": "150.1"},
            {"Date": "20261016", "USD/NTD": "32.838"},
            {"Date": "20261017", "USD/NTD": "-"},
        ]
    )
    yields = 'Date,"2 Yr","10 Yr"\n10/16/2026,4.88,5.15\n10/15/2026,4.86,5.10\n'
    web = Web({RATES: rates, "https://tables.example/yields/2026": yields})

    feed = feed_over(monkeypatch, web, harness)

    readings = await feed.fetch_indicators()
    web.pages[RATES] = "<html>maintenance</html>"
    without_rates = await feed.fetch_indicators()

    assert [(reading.indicator, reading.day, reading.value) for reading in readings] == [
        (WorldIndicator.USD_TWD, date(2026, 10, 15), 32.8),
        (WorldIndicator.USD_TWD, date(2026, 10, 16), 32.838),
        (WorldIndicator.US_10Y_YIELD, date(2026, 10, 16), 5.15),
        (WorldIndicator.US_10Y_YIELD, date(2026, 10, 15), 5.10),
    ]
    assert {reading.indicator for reading in without_rates} == {WorldIndicator.US_10Y_YIELD}
    assert any("World indicators usd_twd were not read" in line for _, line in harness.logger.records)


async def test_a_public_site_builds_only_the_feed_it_may_republish_and_asks_no_other(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = build_harness(now=MORNING)
    tables = {
        RATES: json.dumps([{"Date": "20261016", "USD/NTD": "32.838"}]),
        YIELDS.format(year=2026): 'Date,"10 Yr"\n10/16/2026,5.15\n',
    }
    web = Web({FED: rss(STATEMENT), CNA_WORLD: rss(CHIPS), BBC_BUSINESS: rss(RATE_CUT), **tables})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(web.answer), **kwargs))
    sources = harness.config.sources.model_copy(update={"world": SOURCES})
    public = harness.config.model_copy(update={"audience": Audience.PUBLIC, "sources": sources})
    personal = harness.config.model_copy(update={"sources": sources})

    feed = create_world_feed(public, harness.logger, harness.clock)
    assert feed is not None
    items = await feed.fetch_news()
    readings = await feed.fetch_indicators()
    read_by_public = list(web.asked)
    owners_feed = create_world_feed(personal, harness.logger, harness.clock)
    assert owners_feed is not None
    owners_items = await owners_feed.fetch_news()
    owners_readings = await owners_feed.fetch_indicators()

    assert read_by_public == [FED, YIELDS.format(year=2026)]
    assert [article.source for article in items] == [InformationSource.FEDERAL_RESERVE]
    assert [reading.indicator for reading in readings] == [WorldIndicator.US_10Y_YIELD]
    assert {reading.indicator for reading in owners_readings} == {WorldIndicator.USD_TWD, WorldIndicator.US_10Y_YIELD}
    assert {article.source for article in owners_items} == {
        InformationSource.CNA,
        InformationSource.BBC,
        InformationSource.FEDERAL_RESERVE,
    }


async def test_a_site_that_names_no_feed_or_shows_the_world_to_nobody_builds_none() -> None:
    harness = build_harness(now=MORNING)
    sources = harness.config.sources.model_copy(update={"world": SOURCES})
    hidden = harness.config.features.model_copy(update={"world": FeatureVisibility.OFF})
    unnamed = harness.config.sources.model_copy(update={"world": WorldSources()})

    assert create_world_feed(harness.config.model_copy(update={"sources": unnamed}), harness.logger, harness.clock) is None
    assert (
        create_world_feed(harness.config.model_copy(update={"sources": sources, "features": hidden}), harness.logger, harness.clock)
        is None
    )


# ------------------------------------------------ what is held ------------------------------------------------ #


def news(
    title: str, summary: str, hours_ago: float, source: InformationSource = InformationSource.CNA, now: datetime = MORNING
) -> Article:
    published = now - timedelta(hours=hours_ago)
    return Article(
        stock_id=WORLD,
        source=source,
        title=title,
        content=summary,
        url=f"https://news.example/{abs(hash((title, hours_ago)))}",
        content_type=ContentType.NEWS,
        published_at=published,
        fetched_at=now,
    )


EXPORT_CONTROLS = news("美擴大晶片出口管制 台積電稱影響有限", "美國商務部宣布擴大先進晶片出口管制，台積電表示影響有限。", 3)
FED_CUT = news("Fed cuts rates by a quarter point", "The Federal Reserve lowered its key rate.", 5, InformationSource.BBC)
READINGS = [
    IndicatorReading(indicator=WorldIndicator.USD_TWD, day=TODAY - timedelta(days=4), value=32.8),
    IndicatorReading(indicator=WorldIndicator.USD_TWD, day=TODAY - timedelta(days=3), value=32.838),
    IndicatorReading(indicator=WorldIndicator.US_10Y_YIELD, day=TODAY - timedelta(days=4), value=5.10),
    IndicatorReading(indicator=WorldIndicator.US_10Y_YIELD, day=TODAY - timedelta(days=3), value=5.15),
]
GOOD_REPLY = json.dumps(
    {
        "world": [
            {"text": "美元兌新台幣收 32.838，較前一日上升 0.12%。", "sources": ["S1"], "stocks": []},
            {"text": "美國擴大晶片出口管制，可能與半導體類股有關。", "sources": ["S3"], "stocks": ["2330", "2317"]},
            {"text": "聯準會降息一碼，可能與金融類股有關。", "sources": ["S4"]},
        ]
    },
    ensure_ascii=False,
)


def world_config(daily_ai_calls: int = 60, **brief: object) -> AppConfig:
    config = harness_config()
    page = config.stock_page
    writing = page.system_writing.model_copy(update={"daily_ai_calls": daily_ai_calls})
    prompts = config.prompts.model_copy(
        update={
            "world_brief": INSTRUCTIONS["world_brief_prompt"],
            "stock_brief_advice_phrases": INSTRUCTIONS["stock_brief_advice_phrases"],
        }
    )
    world = config.world.model_copy(update={"brief": config.world.brief.model_copy(update=brief)})
    return config.model_copy(
        update={"stock_page": page.model_copy(update={"system_writing": writing}), "prompts": prompts, "world": world}
    )


def world_site(config: AppConfig | None = None, now: datetime = MORNING, reply: str = GOOD_REPLY) -> tuple[CliHarness, BriefAi]:
    """
    A site whose feeds list the two items and the readings of two days, which lists 台積電 as 2330 and 鴻海 as 2317,
    with the world brief's shipped prompt and the AI of the site's own writing, which a budget of 0 leaves out as the
    wiring does.
    """
    harness = build_harness(now=now, config=config or world_config())
    harness.stocks.stocks = {
        "2330": Stock(stock_id="2330", name="台積電", market=MarketType.TWSE),
        "2317": Stock(stock_id="2317", name="鴻海", market=MarketType.TWSE),
    }
    harness.world_feed.news = [EXPORT_CONTROLS, FED_CUT]
    harness.world_feed.readings = list(READINGS)
    ai = BriefAi(reply)
    harness.system_ai.generate_reply = ai  # pyright: ignore[reportAttributeAccessIssue]
    system_ai = harness.system_ai if harness.config.stock_page.system_writing.enabled else None
    harness.dependencies = replace(harness.dependencies, system_ai_provider=system_ai)
    harness.runtime = compose_runtime(harness.config, harness.logger, harness.clock, harness.dependencies)
    return harness, ai


async def round_of(harness: CliHarness) -> None:
    """One round of the world timer: the feeds read, then the day's brief on the site's own writing."""
    await harness.runtime.signed_out.refresh_world()

    if harness.runtime.system_writer is not None:
        await harness.runtime.system_writer.write_world_brief()


async def test_a_round_keeps_the_feeds_items_and_readings_and_a_second_round_adds_and_embeds_nothing() -> None:
    harness, _ = world_site()
    pipeline = harness.runtime.signed_out

    first = await pipeline.refresh_world()
    second = await pipeline.refresh_world()
    world = await pipeline.load_world()
    readings, held = world.readings, world.news

    assert (first, second) == (WorldUpdate(kept=2, embedded=2, readings=4), WorldUpdate(kept=0, embedded=0, readings=0))
    assert [(article.title, article.source, article.content) for article in held] == [
        (EXPORT_CONTROLS.title, InformationSource.CNA, EXPORT_CONTROLS.content),
        (FED_CUT.title, InformationSource.BBC, FED_CUT.content),
    ]
    assert len(harness.embedder.embedded) == 2 and await harness.articles.stock_ids() == []
    assert [(reading.indicator, reading.value, reading.previous) for reading in readings] == [
        (WorldIndicator.USD_TWD, 32.838, 32.8),
        (WorldIndicator.US_10Y_YIELD, 5.15, 5.10),
    ]
    assert readings[0].change == pytest.approx(32.838 / 32.8 - 1), "a level moves by a share of itself"
    assert readings[1].change == pytest.approx(0.05), "a yield moves in percentage points"


async def test_an_item_whose_feed_gave_no_time_is_not_kept_and_an_old_one_leaves_with_its_retention() -> None:
    harness, _ = world_site()
    undated = replace(news("No time", "", 0), published_at=MORNING, fetched_at=MORNING)
    harness.world_feed.news = [EXPORT_CONTROLS, undated]
    pipeline = harness.runtime.signed_out

    await pipeline.refresh_world()
    kept = [article.title for article in await harness.articles.latest(WORLD, 10)]
    harness.clock.current_time = MORNING + harness.config.world.retention() + timedelta(days=1)
    harness.world_feed.news = [news("後來的新聞", "", 1, now=harness.clock.current_time)]
    await pipeline.refresh_world()

    assert kept == [EXPORT_CONTROLS.title]
    assert [article.title for article in await harness.articles.latest(WORLD, 10)] == ["後來的新聞"]


async def test_the_index_failing_keeps_the_items_and_the_next_round_embeds_them() -> None:
    harness, _ = world_site()
    harness.embedder.failure = RuntimeError("the model file is missing")

    first = await harness.runtime.signed_out.refresh_world()
    harness.embedder.failure = None
    again = await harness.runtime.signed_out.refresh_world()

    assert (first.kept, first.embedded) == (2, 0) and (again.kept, again.embedded) == (0, 2)


# ------------------------------------------------ the day's brief ------------------------------------------------ #


async def test_the_days_brief_is_written_once_from_held_items_on_the_sites_own_model() -> None:
    harness, ai = world_site()
    users_ai_calls: list[object] = []
    harness.ai.generate_reply = users_ai_calls.append  # pyright: ignore[reportAttributeAccessIssue]

    await round_of(harness)
    await round_of(harness)
    world = await harness.runtime.signed_out.load_world()
    briefs, write_at = world.briefs, world.write_at

    assert len(ai.prompts) == 1 and users_ai_calls == [] and write_at == time(7, 30)
    prompt = ai.prompts[0]
    assert "[S1] (indicator, 2026-10-16) USD/TWD exchange rate 32.8380 on 2026-10-16: +0.12% from 32.8000 on 2026-10-15" in prompt
    assert "[S2] (indicator, 2026-10-16) US 10-year Treasury yield 5.15% on 2026-10-16: +0.05 percentage points from 5.10%" in prompt
    assert f"[S3] (world news, 2026-10-19) CNA: {EXPORT_CONTROLS.title} | {EXPORT_CONTROLS.content}" in prompt
    assert f"[S4] (world news, 2026-10-19) BBC: {FED_CUT.title} | {FED_CUT.content}" in prompt
    (brief,) = briefs
    assert (brief.stock_id, brief.day, brief.status, brief.model) == (WORLD, TODAY, BriefStatus.WRITTEN, "claude-haiku-5-5")
    assert brief.company == [] and [sentence.sources for sentence in brief.movement] == [["S1"], ["S3"], ["S4"]]
    assert [(source.key, source.kind, source.origin, source.url) for source in brief.sources] == [
        ("S1", BriefSourceKind.INDICATOR, None, None),
        ("S3", BriefSourceKind.WORLD_NEWS, InformationSource.CNA, EXPORT_CONTROLS.url),
        ("S4", BriefSourceKind.WORLD_NEWS, InformationSource.BBC, FED_CUT.url),
    ]
    assert harness.broker.fills == [] and harness.journal.orders == {}


async def test_a_sentence_links_only_a_listed_stock_an_item_it_cites_names_itself() -> None:
    harness, _ = world_site()

    await round_of(harness)
    (brief,) = (await harness.runtime.signed_out.load_world()).briefs

    assert [sentence.stocks for sentence in brief.movement] == [[], ["2330"], []], "the item names 台積電 and not 鴻海"


async def test_an_item_names_a_listed_stock_by_its_id_as_a_word_or_by_its_whole_name() -> None:
    listed = {"1303": "南亞", "2408": "南亞科", "2330": "台積電", "2030": "彰源", "6505": "台塑化"}

    assert named_stocks("記憶體廠南亞科獲利創新高", listed, 2) == {"2408"}, "the longer name is the one named"
    assert named_stocks("台積電（2330）與 6505-TW 上漲，目標 2030 年", listed, 2) == {"2330", "6505", "2030"}
    assert named_stocks("東南亞各國領袖會議", listed, 2) == {"1303"}, (
        "a name inside another word still matches: the AI must name it too"
    )
    assert named_stocks("TSMC shares rose 12330 points", listed, 2) == frozenset()


async def test_a_reply_keeps_only_cited_sentences_without_links_or_advice() -> None:
    reply = json.dumps(
        {
            "world": [
                {"text": "Nothing the site holds says this.", "sources": []},
                {"text": "This cites a key the prompt never gave.", "sources": ["S99"]},
                {"text": "建議買進半導體類股。", "sources": ["S3"]},
                {"text": "美國擴大晶片出口管制 (https://invented.example/story)。", "sources": ["S3"], "stocks": ["9999"]},
            ],
            "movement": [{"text": "A part the world brief has no use for.", "sources": ["S1"]}],
        },
        ensure_ascii=False,
    )
    harness, _ = world_site(reply=reply)

    await round_of(harness)
    (brief,) = (await harness.runtime.signed_out.load_world()).briefs

    assert [(sentence.text, sentence.sources, sentence.stocks) for sentence in brief.movement] == [
        ("美國擴大晶片出口管制", ["S3"], [])
    ]
    assert [source.key for source in brief.sources] == ["S3"]


async def test_no_brief_is_asked_for_before_its_time_and_each_day_gets_its_own_and_keeps_the_past_ones() -> None:
    early = datetime.combine(TODAY, time(7, 0), MORNING.tzinfo)
    harness, ai = world_site(now=early)

    await round_of(harness)
    before = len(ai.prompts)
    harness.clock.current_time = MORNING
    await round_of(harness)
    harness.clock.current_time = MORNING + timedelta(days=1)
    harness.world_feed.news = [news("油價大漲", "布蘭特原油上漲。", 2, now=harness.clock.current_time)]
    await round_of(harness)
    briefs = (await harness.runtime.signed_out.load_world()).briefs

    assert before == 0 and len(ai.prompts) == 2
    assert [brief.day for brief in briefs] == [TODAY + timedelta(days=1), TODAY]
    assert "油價大漲" in ai.prompts[1] and EXPORT_CONTROLS.title not in ai.prompts[1], "yesterday's items are outside the window"


async def test_a_failed_brief_is_asked_for_again_only_after_the_retry_time() -> None:
    harness, ai = world_site(reply="not a brief")

    await round_of(harness)
    harness.clock.current_time = MORNING + timedelta(minutes=30)
    await round_of(harness)
    failed = await harness.world_briefs.find(WORLD, TODAY)
    ai.reply = GOOD_REPLY
    harness.clock.current_time = MORNING + timedelta(minutes=121)
    await round_of(harness)
    written = await harness.world_briefs.find(WORLD, TODAY)

    assert failed is not None and failed.status == BriefStatus.FAILED
    assert len(ai.prompts) == 2 and written is not None and written.status == BriefStatus.WRITTEN


async def test_a_spent_budget_leaves_the_day_without_a_brief_and_takes_no_claim() -> None:
    harness, ai = world_site()
    ai.failure = AiAllowanceSpentError("The site's own AI calls of today are spent.")
    await harness.runtime.signed_out.refresh_world()
    writer = harness.runtime.system_writer
    assert writer is not None

    with pytest.raises(AiAllowanceSpentError):
        await writer.write_world_brief()

    assert await harness.world_briefs.find(WORLD, TODAY) is None


@pytest.mark.parametrize(
    "off",
    [
        pytest.param({"prompts": harness_config().prompts}, id="no prompt"),
        pytest.param(
            {"features": harness_config().features.model_copy(update={"world": FeatureVisibility.OFF})}, id="the world shown to nobody"
        ),
    ],
)
async def test_a_site_without_the_prompt_or_with_the_world_hidden_asks_no_ai_and_says_it_writes_none(off: dict[str, object]) -> None:
    harness, ai = world_site(world_config().model_copy(update=off))

    await round_of(harness)
    world = await harness.runtime.signed_out.load_world()
    briefs, write_at = world.briefs, world.write_at

    assert ai.prompts == [] and briefs == [] and write_at is None


async def test_a_site_whose_own_writing_is_off_has_no_writer_and_says_it_writes_none() -> None:
    harness, ai = world_site(world_config(daily_ai_calls=0))

    await round_of(harness)

    assert harness.runtime.system_writer is None and ai.prompts == []
    assert (await harness.runtime.signed_out.load_world()).write_at is None


async def test_with_nothing_held_of_the_window_no_brief_is_asked_for() -> None:
    harness, ai = world_site()
    harness.world_feed.news, harness.world_feed.readings = [], []

    await round_of(harness)

    assert ai.prompts == [] and await harness.world_briefs.find(WORLD, TODAY) is None


# ------------------------------------------------ the settings files ------------------------------------------------ #


async def test_an_older_settings_file_starts_with_the_world_off_and_the_start_names_what_it_lacks(tmp_path: Path) -> None:
    texts = repository_texts()
    shipped = texts[SettingsFile.APPSETTING]
    first, last = shipped.index("  world:\n    # The world news feeds"), shipped.index("  ai:\n    grok_base_url")
    prompt_first = texts[SettingsFile.INSTRUCTIONS].index("# Template for the day's world brief")
    prompt_last = texts[SettingsFile.INSTRUCTIONS].index("# Not prompts: what a stock brief looks for")
    older_prompts = texts[SettingsFile.INSTRUCTIONS][:prompt_first] + texts[SettingsFile.INSTRUCTIONS][prompt_last:]
    project = project_with(tmp_path, shipped[:first] + shipped[last:])
    (project / "config" / SettingsFile.INSTRUCTIONS.file_name).write_text(older_prompts, encoding="utf-8")

    config = load_settings(project)
    notices = "\n".join(settings_notices(project))

    assert config.sources.world.news_feeds == [] and config.prompts.world_brief == ""
    assert config.world_brief_due_rule().on is False
    assert "appsetting.yaml does not set sources.world.news_feeds: no world news is read until it does." in notices
    assert "appsetting.yaml does not set sources.world.indicator_feeds: no world indicator is read until it does." in notices
    assert "world_brief_prompt" in notices and "world_brief_query" in notices
    assert load_settings(PROJECT).world_brief_due_rule().on is True
    assert "world" not in "".join(settings_notices(PROJECT))


# ------------------------------------------------ the database ------------------------------------------------ #


async def test_the_readings_are_kept_once_per_indicator_and_day_and_the_newest_is_answered_with_the_one_before(
    database: DatabaseConnector,
) -> None:
    repository = SqlWorldIndicatorRepository(database)

    first = await repository.save(READINGS)
    again = await repository.save(READINGS)
    corrected = await repository.save([replace(READINGS[1], value=32.9)])
    latest = await repository.latest()

    assert (first, again, corrected) == (4, 0, 1)
    assert [(reading.indicator, reading.day, reading.value, reading.previous_day, reading.previous) for reading in latest] == [
        (WorldIndicator.USD_TWD, TODAY - timedelta(days=3), 32.9, TODAY - timedelta(days=4), 32.8),
        (WorldIndicator.US_10Y_YIELD, TODAY - timedelta(days=3), 5.15, TODAY - timedelta(days=4), 5.10),
    ]


async def test_the_world_news_keeps_its_own_retention_and_most_and_is_no_stock_of_the_store(database: DatabaseConnector) -> None:
    clock = MovableClock(MORNING)
    store = SqlArticleStore(database, clock, timedelta(days=365), 100, {WORLD: (timedelta(days=2), 2)})
    of_a_stock = replace(news("公司新聞", "", 72), stock_id="2330", source=InformationSource.NEWS_MEDIA)
    items = [news(f"新聞 {hours}", "", hours) for hours in (1, 2, 3, 72)]

    await store.save([of_a_stock, *items])

    assert [article.title for article in await store.latest(WORLD, 10)] == ["新聞 1", "新聞 2"]
    assert [article.title for article in await store.latest("2330", 10)] == ["公司新聞"]
    assert await store.stock_ids() == ["2330"]


async def test_the_written_world_briefs_are_answered_newest_first(database: DatabaseConnector) -> None:
    harness, _ = world_site()
    await round_of(harness)
    (written,) = (await harness.runtime.signed_out.load_world()).briefs
    repository = SqlStockBriefRepository(database, WorldBriefDTO)

    for day in (TODAY, TODAY - timedelta(days=1), TODAY - timedelta(days=2)):
        await repository.save(replace(written, day=day))

    await repository.save(replace(written, day=TODAY + timedelta(days=1), status=BriefStatus.FAILED))
    recent = await repository.recent(WORLD, 2)

    assert [brief.day for brief in recent] == [TODAY, TODAY - timedelta(days=1)]
    assert recent[0].movement == written.movement and recent[0].sources == written.sources


# ------------------------------------------------ the Web API ------------------------------------------------ #


async def test_the_running_site_reads_the_feeds_and_writes_the_days_brief_by_itself() -> None:
    harness, ai = world_site()

    async with serve(harness) as administrator:
        for _ in range(500):
            world = (await administrator.get("/v1/world")).json()

            if world["briefs"]:
                break

            await asyncio.sleep(0.01)

    assert harness.world_feed.asked == 1 and len(ai.prompts) == 1
    assert [brief["day"] for brief in world["briefs"]] == ["2026-10-19"] and len(world["news"]) == 2


async def test_a_signed_in_viewer_reads_the_world_and_a_visitor_or_a_hidden_feature_does_not() -> None:
    harness, _ = world_site()
    harness.users.add(MEMBER, MEMBER_PASSWORD)
    await round_of(harness)

    async with serve(harness, authorized=False) as visitor:
        refused = await visitor.get("/v1/world")

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as member:
        answered = await member.get("/v1/world")

    hidden = harness.config.features.model_copy(update={"world": FeatureVisibility.OFF})
    harness.config = harness.config.model_copy(update={"features": hidden})
    harness.runtime = compose_runtime(harness.config, harness.logger, harness.clock, harness.dependencies)

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as member:
        not_shown = await member.get("/v1/world")

    assert (refused.status_code, refused.json()["code"]) == (401, "sign_in_required")
    assert (not_shown.status_code, not_shown.json()["code"]) == (403, "feature_hidden")
    world = answered.json()
    assert answered.status_code == 200 and world["write_at"] == "07:30:00"
    assert [(reading["indicator"], reading["value"], reading["previous"]) for reading in world["indicators"]] == [
        ("usd_twd", 32.838, 32.8),
        ("us_10y_yield", 5.15, 5.1),
    ]
    assert world["indicators"][1]["change"] == pytest.approx(0.05)
    assert [(item["source"], item["title"], item["open_text"]) for item in world["news"]] == [
        ("cna", EXPORT_CONTROLS.title, EXPORT_CONTROLS.content),
        ("bbc", FED_CUT.title, FED_CUT.content),
    ]
    (brief,) = world["briefs"]
    assert (brief["status"], brief["day"], brief["model"]) == ("written", "2026-10-19", "claude-haiku-5-5")
    assert brief["movement"][1] == {"text": "美國擴大晶片出口管制，可能與半導體類股有關。", "sources": ["S3"], "stocks": ["2330"]}
    assert Feature.WORLD.value == "world"
