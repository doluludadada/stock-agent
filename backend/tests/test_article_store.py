"""
The article store: what the site read about each stock kept once in the database, with a vector per article in a Chroma
collection of its own; what a site may hold of an article's text; retention; the stocks the timer keeps current; the
searches a stock's AI brief makes, by stock, days and meaning; and the brief as it was while the index finds nothing.
"""

import asyncio
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import chromadb
import pytest
from pydantic import SecretStr
from support.fakes import FakeArticleIndex, FakeTextEmbedder
from support.harness import MARKET_OPEN, MEMBER, MEMBER_PASSWORD, build_harness, daily_history, harness_config, rising_history
from support.settings import shipped_config
from support.web import serve
from test_stock_brief import CONFIRM, announcement, brief_config, brief_harness, context_of
from test_stock_page import article
from trading_stack import MovableClock, SilentLogger

from a_domain.model.market.article import Article
from a_domain.model.system.user import User
from a_domain.model.trading.account import Position
from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.ports.market.daily_close_archive import ExchangeNews, OpenDataDownload
from a_domain.rules.ai.stock_brief import BriefSearch
from a_domain.types.enums import Audience, BriefSourceKind, InformationSource, MarketType, Role, WatchlistType
from a_domain.types.ids import UserId
from b_application.config.app_config import AppConfig
from c_infrastructure.database.chroma.article_index import ChromaArticleIndex
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.mock_trading_dto import MockPosition
from c_infrastructure.database.repositories.article_store import SqlArticleStore
from c_infrastructure.database.repositories.daily_close_archive import SqlDailyCloseArchive
from c_infrastructure.database.repositories.holding_repository import HoldingRepository
from c_infrastructure.database.repositories.user_store import SqlUserStore
from c_infrastructure.database.repositories.users_stocks import SqlUsersStocks
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.feed.stock_feed import HeldStockFeed
from d_presentation.dependencies import article_collection

pytestmark = pytest.mark.asyncio

RETENTION = timedelta(days=365)
REVENUE = "十月營收創新高 年增四成"
PLANT = "董事會決議投資興建新廠"
PRODUCTS = "本公司主要產品為晶圓代工服務"


def store_of(database: DatabaseConnector, clock: MovableClock, max_per_stock: int = 100) -> SqlArticleStore:
    return SqlArticleStore(database, clock, RETENTION, max_per_stock)


def index_of(
    client: chromadb.ClientAPI, embedder: FakeTextEmbedder, clock: MovableClock, name: str = "stock_articles-test"
) -> ChromaArticleIndex:
    return ChromaArticleIndex(client, name, embedder, clock, text_length=300)


def of_stock(stock_id: str, given: Article) -> Article:
    return replace(given, stock_id=stock_id)


def retrieval_config(**brief: object) -> AppConfig:
    """The brief's settings with the three queries a test's kept articles can be told apart by."""
    config = brief_config(**brief)
    queries = {"stock_brief_rise_query": "營收創新高", "stock_brief_fall_query": "營收衰退", "stock_brief_company_query": "主要產品"}
    return config.model_copy(update={"prompts": config.prompts.model_copy(update=queries)})


# ------------------------------------------- what a site may hold ------------------------------------------- #


async def test_a_news_sites_text_is_kept_only_where_the_site_may_read_news_sites_and_a_posts_never() -> None:
    announced = article("公告", InformationSource.TWSE_MOPS, MARKET_OPEN, content="說明" * 10)
    news = article("headline", InformationSource.NEWS_MEDIA, MARKET_OPEN, "https://news.example/a", content="the article's text")
    post = article("[標的] 2330", InformationSource.PTT_STOCK, MARKET_OPEN, "https://ptt.example/1", content="the post's text")
    personal = shipped_config().stock_page.article_store.kept_rule(Audience.PERSONAL.news_articles)
    public = replace(shipped_config().stock_page.article_store.kept_rule(Audience.PUBLIC.news_articles), text_length=6)

    assert [personal.apply(given).content for given in (announced, news, post)] == ["說明" * 10, "the article's text", ""]
    assert [public.apply(given).content for given in (announced, news, post)] == ["說明" * 3, "", ""]
    assert personal.apply(news).open_text is None
    assert {personal.apply(given).key for given in (announced, news, post)} == {announced.key, news.key, post.key}


async def test_an_articles_key_is_its_source_and_address_or_the_time_an_announcement_was_made() -> None:
    news = article("headline", InformationSource.NEWS_MEDIA, MARKET_OPEN, "https://news.example/a")
    announced = article("公告", InformationSource.TWSE_MOPS, MARKET_OPEN)

    assert news.key == replace(news, title="reworded", published_at=MARKET_OPEN + timedelta(hours=1)).key
    assert news.key != replace(news, source=InformationSource.PTT_STOCK).key
    assert announced.key == replace(announced, published_at=announced.published_at.astimezone(tz=None)).key
    assert announced.key != replace(announced, published_at=MARKET_OPEN + timedelta(seconds=1)).key


# ------------------------------------------------ the store ------------------------------------------------ #


async def test_saving_the_same_articles_again_changes_nothing_and_a_reworded_one_is_replaced(database: DatabaseConnector) -> None:
    clock = MovableClock(MARKET_OPEN)
    store = store_of(database, clock)
    news = article("headline", InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(hours=2), "https://news.example/a")
    announced = article("公告", InformationSource.TWSE_MOPS, MARKET_OPEN - timedelta(hours=1), content="說明")
    both_stocks = [news, announced, of_stock("2317", news)]

    first = await store.save(both_stocks)
    clock.current += timedelta(hours=3)
    again = await asyncio.gather(*(store.save(both_stocks) for _ in range(4)))
    reworded = await store.save([replace(news, title="headline, corrected")])
    kept = await store.latest("2330", 10)

    assert (first, again, reworded) == (3, [0, 0, 0, 0], 1)
    assert [(held.title, held.source, held.url, held.open_text) for held in kept] == [
        ("公告", InformationSource.TWSE_MOPS, None, "說明"),
        ("headline, corrected", InformationSource.NEWS_MEDIA, "https://news.example/a", None),
    ]
    assert [held.published_at for held in kept] == [announced.published_at, news.published_at]
    assert kept[0].fetched_at == MARKET_OPEN and kept[1].fetched_at == MARKET_OPEN + timedelta(hours=3)
    assert kept[0].published_at.utcoffset() == timedelta(hours=8) and kept[0].clause == "第51款"
    assert [held.title for held in await store.latest("2317", 10)] == ["headline"]
    assert await store.stock_ids() == ["2317", "2330"]
    assert [held.title for held in await store.find("2330", [news.key, "twse_mops|no such key"])] == ["headline, corrected"]


async def test_retention_drops_what_is_too_old_and_a_stocks_oldest_beyond_its_most(database: DatabaseConnector) -> None:
    clock = MovableClock(MARKET_OPEN)
    store = store_of(database, clock, max_per_stock=3)
    dated = [
        article(f"day {days}", InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=days), f"https://news.example/{days}")
        for days in range(1, 6)
    ]
    too_old = article(
        "last year", InformationSource.NEWS_MEDIA, MARKET_OPEN - RETENTION - timedelta(days=1), "https://news.example/old"
    )
    other = of_stock(
        "2317", article("other stock", InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=300), "https://news.example/o")
    )

    saved = await store.save([*dated, too_old, other])
    clock.current += timedelta(days=100)
    await store.save([article("today", InformationSource.NEWS_MEDIA, clock.current - timedelta(hours=1), "https://news.example/t")])

    assert saved == 6
    assert [held.title for held in await store.latest("2330", 10)] == ["today", "day 1", "day 2"]
    assert await store.latest("2317", 10) == []


# ------------------------------------------------ the index ------------------------------------------------ #


async def test_an_unchanged_article_is_never_embedded_again_and_a_gone_one_leaves_the_index() -> None:
    clock, embedder = MovableClock(MARKET_OPEN), FakeTextEmbedder()
    index = index_of(chromadb.EphemeralClient(), embedder, clock, "stock_articles-unchanged")
    revenue = article(REVENUE, InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=1), "https://news.example/r")
    plant = article("公告", InformationSource.TWSE_MOPS, MARKET_OPEN - timedelta(days=2), content=PLANT)

    first = await index.sync("2330", [revenue, plant])
    again = await index.sync("2330", [revenue, plant])
    reworded = await index.sync("2330", [revenue, replace(plant, content=PRODUCTS)])
    embedded = list(embedder.embedded)
    gone = await index.sync("2330", [revenue])

    assert (first, again, reworded, gone) == (2, 0, 1, 0)
    assert embedded == [REVENUE, f"公告\n{PLANT}", f"公告\n{PRODUCTS}"]
    assert await index.search("2330", PRODUCTS, None, None, 5) == [revenue.key]


async def test_a_search_stays_inside_the_stock_and_the_days_and_answers_the_closest_first() -> None:
    clock, embedder = MovableClock(MARKET_OPEN), FakeTextEmbedder()
    index = index_of(chromadb.EphemeralClient(), embedder, clock, "stock_articles-search")
    day = MARKET_OPEN.date()
    revenue = article(REVENUE, InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=1), "https://news.example/r")
    plant = article(PLANT, InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=3), "https://news.example/p")
    midnight = article(
        REVENUE,
        InformationSource.PTT_STOCK,
        datetime.combine(day - timedelta(days=10), datetime.min.time(), MARKET_OPEN.tzinfo),
        "https://ptt.example/1",
    )
    await index.sync("2330", [revenue, plant, midnight])
    await index.sync("2317", [of_stock("2317", revenue)])

    assert await index.search("2330", "營收創新高", None, None, 2) == [revenue.key, midnight.key]
    assert await index.search("2330", "營收創新高", day - timedelta(days=3), None, 5) == [revenue.key, plant.key]
    assert await index.search("2330", "營收創新高", day - timedelta(days=10), day - timedelta(days=3), 5) == [midnight.key]
    assert await index.search("2330", "營收創新高", None, day - timedelta(days=10), 5) == []
    assert await index.search("2317", "興建新廠", None, None, 5) == [revenue.key]
    assert await index.search("1101", "營收創新高", None, None, 5) == []


async def test_lost_vectors_are_computed_again_from_the_kept_articles_and_kept_ones_survive_a_restart(
    database: DatabaseConnector, tmp_path: Path
) -> None:
    clock, embedder = MovableClock(MARKET_OPEN), FakeTextEmbedder()
    store = store_of(database, clock)
    revenue = article(REVENUE, InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=1), "https://news.example/r")
    plant = article(PLANT, InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=3), "https://news.example/p")
    await store.save([revenue, plant])
    kept = await store.latest("2330", 100)

    before = await index_of(chromadb.PersistentClient(path=str(tmp_path / "chroma")), embedder, clock).sync("2330", kept)
    restarted = index_of(chromadb.PersistentClient(path=str(tmp_path / "chroma")), embedder, clock)
    after_restart = await restarted.sync("2330", kept)
    lost = index_of(chromadb.PersistentClient(path=str(tmp_path / "empty")), embedder, clock)
    nothing = await lost.search("2330", "興建新廠", None, None, 1)
    rebuilt = await lost.sync("2330", kept)

    assert (before, after_restart, nothing, rebuilt) == (2, 0, [], 2)
    assert await restarted.search("2330", "興建新廠", None, None, 1) == [plant.key]
    assert await lost.search("2330", "興建新廠", None, None, 1) == [plant.key]
    assert [held.title for held in await store.find("2330", await lost.search("2330", "興建新廠", None, None, 1))] == [PLANT]


async def test_another_embedding_model_or_reading_length_has_a_collection_of_its_own() -> None:
    config = shipped_config()
    store = config.stock_page.article_store
    other_model = store.model_copy(update={"embedding": store.embedding.model_copy(update={"revision": "0" * 40})})
    longer = store.model_copy(update={"embedded_length": store.embedded_length + 1})
    names = {
        article_collection(config.model_copy(update={"stock_page": config.stock_page.model_copy(update={"article_store": changed})}))
        for changed in (store, other_model, longer)
    }

    assert len(names) == 3 and all(name.startswith("stock_articles-") for name in names)


# ------------------------------------------- the stocks that matter ------------------------------------------- #


async def test_the_stocks_users_hold_or_watch_are_read_one_user_at_a_time_and_name_no_user(database: DatabaseConnector) -> None:
    clock = MovableClock(MARKET_OPEN)
    users = SqlUserStore(database, SecretStr("A" * 43), SilentLogger())
    alice, bob = UserId("u-alice"), UserId("u-bob")

    for user_id in (alice, bob):
        named = User(user_id=user_id, username=user_id, email=f"{user_id}@example.com", role=Role.USER, created_at=MARKET_OPEN)
        await users.create(named, SecretStr("a long enough password"))

    watching = WatchlistRepository(database.for_owner(alice), SilentLogger(), clock)
    await watching.save(
        [
            WatchlistEntry(stock_id="2330", watchlist_type=WatchlistType.MANUAL, created_at=MARKET_OPEN, expires_at=None),
            WatchlistEntry(
                stock_id="1101",
                watchlist_type=WatchlistType.MANUAL,
                created_at=MARKET_OPEN,
                expires_at=MARKET_OPEN - timedelta(days=1),
            ),
        ]
    )
    await HoldingRepository(database.for_owner(bob)).save(
        Position(stock_id="2317", quantity=1000, average_cost=100.0, opened_at=MARKET_OPEN)
    )

    async with database.for_owner(bob).owner_session() as session:
        session.add(MockPosition(owner_id=bob, stock_id="2454", quantity=1000, average_cost=900.0))
        await session.commit()

    assert await SqlUsersStocks(database, clock).held_or_watched() == {"2330", "2317", "2454"}


async def test_the_timer_reads_the_stocks_users_hold_or_watch_each_once_up_to_its_most() -> None:
    store = harness_config().stock_page.article_store.model_copy(update={"refresh_stocks": 3})
    config = harness_config().model_copy(
        update={"stock_page": harness_config().stock_page.model_copy(update={"article_store": store})}
    )
    harness = build_harness(config=config)
    harness.users_stocks.stock_ids = {"9999", "1101", "2330", "2317"}

    for stock_id in sorted(harness.users_stocks.stock_ids):
        harness.list_stock(stock_id, rising_history(100.0))
        harness.news.articles[stock_id] = [
            replace(article(REVENUE, InformationSource.NEWS_MEDIA, MARKET_OPEN, f"https://news.example/{stock_id}"), stock_id=stock_id)
        ]

    stocks, embedded = await harness.runtime.signed_out.refresh_article_store()
    again = await harness.runtime.signed_out.refresh_article_store()

    expected = ["1101", "2317", "2330"]
    assert (stocks, embedded, again) == (3, 3, (3, 0))
    assert harness.news.requested == expected
    assert await harness.articles.stock_ids() == expected
    assert harness.embedder.embedded == [REVENUE] * 3


async def test_two_stocks_fetches_from_the_sites_start_at_least_the_pause_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = MovableClock(MARKET_OPEN)
    harness = build_harness()
    waited: list[float] = []

    async def wait(seconds: float) -> None:
        waited.append(seconds)
        clock.current += timedelta(seconds=seconds)

    monkeypatch.setattr(asyncio, "sleep", wait)
    feed = HeldStockFeed(harness.news, None, clock, timedelta(minutes=30), 10, timedelta(seconds=2), SilentLogger())

    await feed.fetch("2330", 5)
    await feed.fetch("2317", 5)
    await feed.fetch("2317", 5)
    clock.current += timedelta(seconds=5)
    await feed.fetch("2454", 5)

    assert waited == [0.0, 2.0, 0.0]
    assert harness.news.requested == ["2330", "2317", "2454"]


# ------------------------------------------------ the stock page ------------------------------------------------ #


async def test_the_stock_page_lists_what_the_store_keeps_after_the_sites_stopped_serving_it() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))
    earlier = article(
        "earlier headline", InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=3), "https://news.example/a", content="its text"
    )
    later = article("later headline", InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(hours=1), "https://news.example/b")
    harness.news.articles["2330"] = [earlier]

    async with serve(harness) as client:
        first = await client.get("/v1/market/stocks/2330/news")
        harness.clock.current_time += timedelta(hours=1)
        harness.news.articles["2330"] = [later]
        second = await client.get("/v1/market/stocks/2330/news")

    assert [item["title"] for item in first.json()["items"]] == ["earlier headline"]
    assert [(item["title"], item["url"], item["open_text"]) for item in second.json()["items"]] == [
        ("later headline", "https://news.example/b", None),
        ("earlier headline", "https://news.example/a", None),
    ]
    assert "its text" not in first.text + second.text
    assert [(kept.title, kept.content) for kept in await harness.articles.latest("2330", 10)][1] == ("earlier headline", "its text")
    assert harness.embedder.embedded == []


async def test_a_public_site_keeps_announcements_with_their_text_and_reads_no_news_site() -> None:
    harness = build_harness(config=harness_config().model_copy(update={"audience": Audience.PUBLIC}))
    harness.list_stock("2330", rising_history(100.0))
    announced = article("澄清媒體報導", InformationSource.TWSE_MOPS, MARKET_OPEN - timedelta(hours=1), content="本公司說明如下")
    harness.archive.announcements[("2330", announced.published_at)] = announced
    harness.news.articles["2330"] = [article("cnyes says", InformationSource.NEWS_MEDIA, MARKET_OPEN, "https://news.example/a")]

    await harness.runtime.signed_out.load_stock_news("2330")

    assert [(kept.source, kept.content) for kept in await harness.articles.latest("2330", 10)] == [
        (InformationSource.TWSE_MOPS, "本公司說明如下")
    ]
    assert harness.news.requested == []


# ------------------------------------------------- the archive ------------------------------------------------- #


async def test_the_archive_names_every_announcement_and_a_news_item_once_for_each_stock_its_title_names(
    database: DatabaseConnector,
) -> None:
    clock = MovableClock(MARKET_OPEN)
    archive = SqlDailyCloseArchive(database, clock, shipped_config().sources.exchange, 7, SilentLogger())
    old = article("去年的公告", InformationSource.TWSE_MOPS, MARKET_OPEN - timedelta(days=400))
    recent = article("公告", InformationSource.TWSE_MOPS, MARKET_OPEN - timedelta(days=40), content="說明")
    naming_two = ExchangeNews(
        url="https://twse.example/n1", title="台積電(2330)及鴻海(2317)召開法人說明會", published_on=date(2026, 9, 1)
    )
    download = OpenDataDownload(
        stocks=[],
        indexes={market: [] for market in MarketType},
        material_information=[old, recent],
        quarter_eps={},
        valuation_ratios=[],
        financial_reports=[],
        monthly_revenues=[],
        exchange_news=[naming_two],
    )
    await archive.save(download)

    found = await archive.archived_articles(MARKET_OPEN - RETENTION)

    assert sorted((held.stock_id, held.source, held.title) for held in found) == [
        ("2317", InformationSource.TWSE_NEWS, naming_two.title),
        ("2330", InformationSource.TWSE_MOPS, "公告"),
        ("2330", InformationSource.TWSE_NEWS, naming_two.title),
    ]
    assert len({(held.stock_id, held.key) for held in found}) == 3


async def test_the_backfill_keeps_the_archives_articles_of_listed_stocks_once_and_embeds_each_once() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))
    listed = [announcement(f"公告 {number}", PLANT, MARKET_OPEN - timedelta(days=40 * number)) for number in (1, 2)]
    unlisted = replace(announcement("下市公司公告", PLANT), stock_id="9998")
    too_old = announcement("三年前", PLANT, MARKET_OPEN - timedelta(days=1100))
    harness.archive.announcements = {(given.stock_id, given.published_at): given for given in (*listed, unlisted, too_old)}

    first = await harness.runtime.signed_out.backfill_article_store()
    again = await harness.runtime.signed_out.backfill_article_store()
    harness.article_index.entries.clear()
    after_loss = await harness.runtime.signed_out.backfill_article_store()

    assert (first, again, after_loss) == ((2, 1, 2), (0, 1, 0), (0, 1, 2))
    assert [kept.title for kept in await harness.articles.latest("2330", 10)] == ["公告 1", "公告 2"]
    assert harness.news.requested == []


# -------------------------------------------------- the brief -------------------------------------------------- #


async def test_a_brief_searches_the_window_for_the_moves_direction_the_days_before_it_and_the_long_past_for_the_company() -> None:
    rule = retrieval_config(
        window_sessions=5, articles=6, lead_days=10, lead_articles=2, company_days=400, company_articles=3
    ).stock_page.brief
    queries = ("營收創新高", "營收衰退", "主要產品")
    today = MARKET_OPEN.date()
    rising, falling = daily_history([100.0 + step for step in range(10)]), daily_history([100.0 - step for step in range(10)])
    first = rising[-5].ts.date()

    assert rule.search_rule(*queries).apply(rising, today) == [
        BriefSearch(query="營收創新高", first=first, last=None, limit=6),
        BriefSearch(query="營收創新高", first=first - timedelta(days=10), last=first, limit=2),
        BriefSearch(query="主要產品", first=today - timedelta(days=400), last=None, limit=3),
    ]
    assert [search.query for search in rule.search_rule(*queries).apply(falling, today)] == ["營收衰退", "營收衰退", "主要產品"]
    assert [search.query for search in rule.search_rule(*queries).apply([], today)] == ["主要產品"]
    assert rule.search_rule("", "", " ").apply(rising, today) == []
    assert [
        search.query for search in replace(rule.search_rule(*queries), lead_articles=0, company_articles=0).apply(rising, today)
    ] == ["營收創新高"]


async def test_a_brief_rests_on_the_kept_articles_its_searches_find_each_once_and_cites_them_as_sources() -> None:
    harness, ai = brief_harness(retrieval_config(window_sessions=5, articles=2, lead_days=10, lead_articles=1, company_articles=1))
    window_first = MARKET_OPEN - timedelta(days=5)
    in_window = [
        article(
            REVENUE,
            InformationSource.NEWS_MEDIA,
            MARKET_OPEN - timedelta(days=1),
            "https://news.example/r",
            content="body the page never shows",
        ),
        article("營收創新高 法人看好", InformationSource.PTT_STOCK, MARKET_OPEN - timedelta(days=2), "https://ptt.example/1"),
        article("股東會紀念品發放", InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=3), "https://news.example/g"),
    ]
    lead = article("九月營收創新高", InformationSource.NEWS_MEDIA, window_first - timedelta(days=4), "https://news.example/l")
    long_past = announcement("公告本公司簡介", PRODUCTS, MARKET_OPEN - timedelta(days=200))
    harness.news.articles["2330"] = in_window[:1]
    await harness.articles.save([*in_window[1:], lead, long_past])
    cited = {
        "company": [{"text": "It makes wafers.", "sources": ["S7"]}],
        "movement": [{"text": "It rose.", "sources": ["S2", "S4", "S6"]}],
    }
    ai.reply = json.dumps(cited)

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as member:
        written = await member.post("/v1/market/stocks/2330/brief", json=CONFIRM)

    facts = [line for line in ai.prompts[0].splitlines() if line.startswith("[S")]
    assert written.status_code == 200 and len(ai.prompts) == 1
    assert facts[3:] == [
        f"[S4] (news, {(MARKET_OPEN - timedelta(days=1)).date()}) {REVENUE}",
        f"[S5] (post, {(MARKET_OPEN - timedelta(days=2)).date()}) 營收創新高 法人看好",
        f"[S6] (news, {lead.published_at.date()}) 九月營收創新高",
        f"[S7] (announcement, {long_past.published_at.date()}) 公告本公司簡介 | {PRODUCTS}",
    ]
    assert "body the page never shows" not in ai.prompts[0] and "股東會紀念品" not in ai.prompts[0]
    assert [(source["key"], source["kind"], source["title"], source["url"]) for source in written.json()["today"]["sources"]] == [
        ("S2", "price", None, None),
        ("S4", "news", REVENUE, "https://news.example/r"),
        ("S6", "news", "九月營收創新高", "https://news.example/l"),
        ("S7", "announcement", "公告本公司簡介", None),
    ]
    assert sorted(set(harness.embedder.embedded) - {"營收創新高", "主要產品"}) == sorted(
        [
            f"{REVENUE}\nbody the page never shows",
            "營收創新高 法人看好",
            "股東會紀念品發放",
            "九月營收創新高",
            f"公告本公司簡介\n{PRODUCTS}",
        ]
    )


async def test_an_article_two_searches_found_and_a_headline_repeated_daily_reach_the_prompt_once() -> None:
    daily = [
        article("外資近5日賣超個股", InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=days), f"https://news.example/{days}")
        for days in (1, 2, 3)
    ]
    furnace = announcement("公告本公司取得機器設備", "高爐 41.46億元", MARKET_OPEN - timedelta(days=4))
    sinter = announcement("公告本公司取得機器設備", "燒結設備 13.43億元", MARKET_OPEN - timedelta(days=4, minutes=1))
    long_past = announcement("公告本公司簡介", PRODUCTS, MARKET_OPEN - timedelta(days=200))

    context = context_of(brief_config(), [], [daily[2], furnace, daily[0], long_past, sinter, daily[1], long_past, furnace])

    assert [fact.text for fact in context.facts[3:]] == [
        "外資近5日賣超個股",
        "公告本公司取得機器設備 | 高爐 41.46億元",
        "公告本公司取得機器設備 | 燒結設備 13.43億元",
        f"公告本公司簡介 | {PRODUCTS}",
    ]
    assert context.facts[3].source.dated == daily[0].published_at.date()


async def test_while_the_index_finds_nothing_the_brief_is_written_as_before_from_the_windows_newest_articles() -> None:
    harness, ai = brief_harness(retrieval_config(articles=2))
    newest = [
        article(f"notice {days}", InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=days), f"https://news.example/{days}")
        for days in (1, 2, 3)
    ]
    long_past = announcement("公告本公司簡介", PRODUCTS, MARKET_OPEN - timedelta(days=200))
    await harness.articles.save([*newest, long_past])
    harness.embedder.failure = OSError("the model's files cannot be fetched")

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as member:
        written = await member.post("/v1/market/stocks/2330/brief", json=CONFIRM)

    facts = [line for line in ai.prompts[0].splitlines() if line.startswith("[S")]
    assert (written.status_code, written.json()["today"]["status"]) == (200, "written")
    assert [fact.split(") ")[1] for fact in facts[3:]] == ["notice 1", "notice 2"]
    assert any(level == "warning" and "article index" in message for level, message in harness.logger.records)


async def test_a_stock_with_no_kept_article_gets_the_brief_it_got_before_the_store() -> None:
    plain, plain_ai = brief_harness()
    searching, searching_ai = brief_harness(retrieval_config())

    for harness in (plain, searching):
        async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as member:
            await member.post("/v1/market/stocks/2330/brief", json=CONFIRM)

    assert plain_ai.prompts == searching_ai.prompts and len(plain_ai.prompts) == 1
    assert [source.kind for source in (await searching.briefs.find("2330", MARKET_OPEN.date())).sources if source.title] == []
    assert BriefSourceKind.NEWS.value not in plain_ai.prompts[0].split("Facts:")[1].split("Write one part")[0]


async def test_the_fake_index_answers_as_the_chroma_index_does() -> None:
    clock = MovableClock(MARKET_OPEN)
    day = MARKET_OPEN.date()
    given = [
        article(REVENUE, InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=1), "https://news.example/r"),
        article(PLANT, InformationSource.NEWS_MEDIA, MARKET_OPEN - timedelta(days=3), "https://news.example/p"),
        article("公告", InformationSource.TWSE_MOPS, MARKET_OPEN - timedelta(days=9), content=PRODUCTS),
    ]
    real = index_of(chromadb.EphemeralClient(), FakeTextEmbedder(), clock, "stock_articles-parity")
    fake = FakeArticleIndex(FakeTextEmbedder())
    asked = [
        ("營收創新高", None, None, 3),
        ("主要產品", day - timedelta(days=9), day - timedelta(days=1), 2),
        ("興建新廠", None, day, 1),
    ]

    for index in (real, fake):
        assert (await index.sync("2330", given), await index.sync("2330", given)) == (3, 0)

    for query in asked:
        assert await real.search("2330", *query) == await fake.search("2330", *query)
