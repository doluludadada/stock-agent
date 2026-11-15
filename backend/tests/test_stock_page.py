"""
The stock page's news, ranking place and analysis over the Web API: who may read each, what a public site serves, how
the fetched news is held and what a failing source leaves, and that the feed dates by Taipei on a server in UTC.
"""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from support.fakes import FakeNewsProvider, FakeSocialMediaProvider
from support.harness import MARKET_OPEN, MEMBER, MEMBER_PASSWORD, build_harness, harness_config, rising_history
from support.settings import shipped_config
from support.web import app_of, client_at, serve, sign_in
from test_ranking import bars, market
from test_ranking_rule import revenue
from trading_stack import MovableClock, SilentLogger, StockDirectory

from a_domain.model.market.article import Article
from a_domain.ports.market.daily_close_archive import ValuationRatios
from a_domain.rules.fundamentals.trailing_eps import QuarterEps
from a_domain.types.enums import Audience, ContentType, InformationSource, MarketType
from a_domain.types.values import FiscalQuarter
from c_infrastructure.ai_models.base import BaseAIAdapter
from c_infrastructure.feed.news_provider import NewsProvider
from c_infrastructure.feed.ptt_provider import PttProvider
from c_infrastructure.feed.stock_feed import HeldStockFeed
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

pytestmark = pytest.mark.asyncio

FRESHNESS = timedelta(minutes=30)
NEW_YEARS_EVE_UTC = datetime(2026, 12, 31, 16, 30, tzinfo=UTC)
"""00:30 on 2027-01-01 in Taipei, while a server in UTC still reads 2026-12-31."""


def article(title: str, source: InformationSource, published_at: datetime, url: str | None = None, content: str = "") -> Article:
    """One article published at `published_at` and fetched a minute later."""
    return Article(
        stock_id="2330",
        source=source,
        title=title,
        content=content or title,
        url=url,
        content_type=ContentType.FACT if source is InformationSource.TWSE_MOPS else ContentType.NEWS,
        published_at=published_at,
        fetched_at=published_at + timedelta(minutes=1),
        clause="第51款" if source is InformationSource.TWSE_MOPS else None,
    )


def held_feed(clock: MovableClock, held_stocks: int = 10) -> tuple[HeldStockFeed, FakeNewsProvider, FakeSocialMediaProvider]:
    news, board = FakeNewsProvider(), FakeSocialMediaProvider()
    news.articles["2330"] = [article("cnyes says", InformationSource.NEWS_MEDIA, MARKET_OPEN, "https://news.example/a")]
    board.stock_posts["2330"] = [article("[標的] 2330", InformationSource.PTT_STOCK, MARKET_OPEN, "https://ptt.example/1")]
    return HeldStockFeed(news, board, clock, FRESHNESS, held_stocks, timedelta(0), SilentLogger()), news, board


async def test_a_second_page_view_inside_the_freshness_window_reaches_no_site() -> None:
    clock = MovableClock(MARKET_OPEN)
    feed, news, board = held_feed(clock)

    first = await feed.fetch("2330", 10)
    clock.current += FRESHNESS
    second = await feed.fetch("2330", 10)

    assert [item.title for item in first] == [item.title for item in second] == ["cnyes says", "[標的] 2330"]
    assert (news.requested, board.searched) == (["2330"], ["2330"])


async def test_a_page_view_after_the_window_asks_the_sites_again() -> None:
    clock = MovableClock(MARKET_OPEN)
    feed, news, board = held_feed(clock)

    await feed.fetch("2330", 10)
    clock.current += FRESHNESS + timedelta(seconds=1)
    news.articles["2330"] = [article("newer", InformationSource.NEWS_MEDIA, clock.current, "https://news.example/b")]
    again = await feed.fetch("2330", 10)

    assert [item.title for item in again] == ["newer", "[標的] 2330"]
    assert (news.requested, board.searched) == (["2330", "2330"], ["2330", "2330"])


async def test_visitors_who_open_the_same_page_together_share_one_fetch() -> None:
    feed, news, _ = held_feed(MovableClock(MARKET_OPEN))

    answers = await asyncio.gather(*(feed.fetch("2330", 10) for _ in range(5)))

    assert news.requested == ["2330"]
    assert all([item.title for item in answer] == ["cnyes says", "[標的] 2330"] for answer in answers)


async def test_a_source_that_fails_keeps_what_was_held_of_it_and_is_not_asked_again_inside_the_window() -> None:
    clock = MovableClock(MARKET_OPEN)
    feed, news, board = held_feed(clock)

    await feed.fetch("2330", 10)
    clock.current += FRESHNESS + timedelta(seconds=1)
    news.failure = httpx.ConnectError("cnyes is down")
    board.stock_posts["2330"] = []
    degraded = await feed.fetch("2330", 10)
    await feed.fetch("2330", 10)

    assert [item.title for item in degraded] == ["cnyes says", "[標的] 2330"]
    assert len(news.requested) == 2


async def test_a_source_that_fails_before_anything_is_held_answers_nothing_not_an_error() -> None:
    feed, news, _ = held_feed(MovableClock(MARKET_OPEN))
    news.failure = httpx.ConnectError("cnyes is down")

    assert [item.title for item in await feed.fetch("2330", 10)] == ["[標的] 2330"]


async def test_only_the_stocks_asked_most_recently_stay_held() -> None:
    feed, news, _ = held_feed(MovableClock(MARKET_OPEN), held_stocks=2)

    for stock_id in ("2330", "2317", "2454", "2330"):
        await feed.fetch(stock_id, 10)

    assert news.requested == ["2330", "2317", "2454", "2330"]


async def test_stocks_asked_together_reach_the_sites_one_stock_at_a_time() -> None:
    news, asking, most = FakeNewsProvider(), 0, 0
    answer = news.fetch_news

    async def answer_after_a_moment(stock_id: str, limit: int = 10) -> list[Article]:
        nonlocal asking, most
        asking += 1
        most = max(most, asking)
        await asyncio.sleep(0)
        asking -= 1
        return await answer(stock_id, limit)

    news.fetch_news = answer_after_a_moment
    feed = HeldStockFeed(news, None, MovableClock(MARKET_OPEN), FRESHNESS, 10, timedelta(0), SilentLogger())

    await asyncio.gather(*(feed.fetch(stock_id, 10) for stock_id in ("2330", "2317", "2454", "2603")))

    assert (most, sorted(news.requested)) == (1, ["2317", "2330", "2454", "2603"])


async def test_a_visitor_is_refused_a_stocks_news_before_any_site_is_asked_and_a_signed_in_user_reads_it() -> None:
    harness = build_harness()
    harness.users.add(MEMBER, MEMBER_PASSWORD)
    harness.list_stock("2330", rising_history(100.0))
    harness.news.articles["2330"] = [article("cnyes says", InformationSource.NEWS_MEDIA, MARKET_OPEN, "https://news.example/a")]

    async with app_of(harness) as app, client_at(app) as visitor, client_at(app) as member:
        refused = await visitor.get("/v1/market/stocks/2330/news")
        asked_for_the_visitor = list(harness.news.requested)
        await sign_in(member, MEMBER.username, MEMBER_PASSWORD)
        read = await member.get("/v1/market/stocks/2330/news")

    assert (refused.status_code, refused.json()["code"], asked_for_the_visitor) == (401, "sign_in_required", [])
    assert (read.status_code, [item["title"] for item in read.json()["items"]]) == (200, ["cnyes says"])
    assert harness.news.requested == ["2330"]


async def test_a_personal_stock_page_serves_announcements_news_and_posts_newest_first_with_only_open_text() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))
    announced = article("澄清媒體報導", InformationSource.TWSE_MOPS, MARKET_OPEN - timedelta(hours=1), content="本公司說明如下")
    harness.archive.announcements[("2330", announced.published_at)] = announced
    harness.news.articles["2330"] = [
        article("cnyes says", InformationSource.NEWS_MEDIA, MARKET_OPEN, "https://news.example/a", content="the article's full text")
    ]
    harness.social.stock_posts["2330"] = [
        article("[標的] 2330", InformationSource.PTT_STOCK, MARKET_OPEN - timedelta(days=1), "https://ptt.example/1")
    ]

    async with serve(harness) as client:
        answer = await client.get("/v1/market/stocks/2330/news")
        await client.get("/v1/market/stocks/2330/news")

    items = answer.json()["items"]
    assert answer.status_code == 200
    assert [(item["source"], item["title"], item["url"]) for item in items] == [
        ("news_media", "cnyes says", "https://news.example/a"),
        ("twse_mops", "澄清媒體報導", None),
        ("ptt_stock", "[標的] 2330", "https://ptt.example/1"),
    ]
    assert [item["open_text"] for item in items] == [None, "本公司說明如下", None]
    assert "the article's full text" not in answer.text
    assert harness.news.requested == ["2330"]


async def test_an_article_stamped_with_its_fetch_time_for_want_of_a_publication_time_is_left_out() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))
    undated = replace(article("an ad", InformationSource.NEWS_MEDIA, MARKET_OPEN, "https://news.example/ad"), fetched_at=MARKET_OPEN)
    harness.news.articles["2330"] = [undated, article("dated", InformationSource.NEWS_MEDIA, MARKET_OPEN, "https://news.example/a")]

    async with serve(harness) as client:
        answer = await client.get("/v1/market/stocks/2330/news")

    assert [item["title"] for item in answer.json()["items"]] == ["dated"]


async def test_a_public_stock_page_serves_the_archive_alone_and_reaches_no_news_site_or_board() -> None:
    harness = build_harness(config=harness_config().model_copy(update={"audience": Audience.PUBLIC}))
    harness.list_stock("2330", rising_history(100.0))
    announced = article("澄清媒體報導", InformationSource.TWSE_MOPS, MARKET_OPEN - timedelta(hours=1))
    harness.archive.announcements[("2330", announced.published_at)] = announced
    harness.news.articles["2330"] = [article("cnyes says", InformationSource.NEWS_MEDIA, MARKET_OPEN, "https://news.example/a")]

    async with serve(harness) as client:
        answer = await client.get("/v1/market/stocks/2330/news")

    assert [item["source"] for item in answer.json()["items"]] == ["twse_mops"]
    assert (harness.news.requested, harness.social.searched) == ([], [])


async def test_a_code_that_is_not_listed_is_refused_before_any_site_is_asked() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))

    async with serve(harness) as client:
        answer = await client.get("/v1/market/stocks/9999/news")

    assert answer.status_code == 404
    assert harness.news.requested == []


async def test_the_analysis_is_public_and_reads_the_archive_and_the_held_mops_pages_without_a_fetch() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))
    session = date(2026, 10, 16)
    harness.archive.valuation_ratios[("2330", session)] = ValuationRatios("2330", session, 24.75, 1.03, 8.61)

    for quarter, eps in ((FiscalQuarter(2025, 2), 30.0), (FiscalQuarter(2026, 2), 36.0)):
        harness.fundamentals.held_pages[(MarketType.TWSE, quarter)] = QuarterEps(quarter, {"2330": eps}, MARKET_OPEN)

    async with serve(harness, authorized=False) as client:
        answer = await client.get("/v1/market/stocks/2330/analysis")

    body = answer.json()
    assert answer.status_code == 200
    assert [(result["quarter"], result["eps_year_over_year"]) for result in body["earnings"]["quarters"]] == [
        ({"year": 2025, "quarter": 2}, None),
        ({"year": 2026, "quarter": 2}, pytest.approx(0.2)),
    ]
    assert body["valuation"]["pe_ratio"] == {"latest": 24.75, "median": None, "sessions": 1}
    assert body["readings"] == [
        {"kind": "no_revenue", "count": None},
        {"kind": "eps_up", "count": 1},
        {"kind": "valuation_history_short", "count": 1},
    ]
    assert harness.fundamentals.requested == []


async def test_a_public_analysis_reads_no_mops_page() -> None:
    harness = build_harness(config=harness_config().model_copy(update={"audience": Audience.PUBLIC}))
    quarter = FiscalQuarter(2026, 2)
    harness.fundamentals.held_pages[(MarketType.TWSE, quarter)] = QuarterEps(quarter, {"2330": 36.0}, MARKET_OPEN)

    async with serve(harness, authorized=False) as client:
        answer = await client.get("/v1/market/stocks/2330/analysis")

    assert answer.json()["earnings"]["quarters"] == []


async def test_the_financials_read_the_archives_quarters_and_revenue_and_no_mops_page_or_valuation_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness()
    harness.archive.held_financials["2330"] = ([], [revenue("2330", 2026, 9, 100.0)])
    read: list[str] = []

    async def no_ratios(stock_id: str) -> list[ValuationRatios]:
        read.append(f"valuation history of {stock_id}")
        return []

    async def no_page(market: MarketType, quarter: FiscalQuarter) -> QuarterEps | None:
        read.append(f"{market} page of {quarter}")
        return None

    monkeypatch.setattr(harness.archive, "valuation_history", no_ratios)
    monkeypatch.setattr(harness.fundamentals, "load_page", no_page)

    async with serve(harness, authorized=False) as client:
        financials = await client.get("/v1/market/stocks/2330/financials")
        unread = list(read)
        await client.get("/v1/market/stocks/2330/analysis")

    assert [(month["year"], month["month"]) for month in financials.json()["monthly_revenues"]] == [(2026, 9)]
    assert unread == []
    assert "valuation history of 2330" in read and len(read) > 1


async def test_a_stocks_score_is_its_place_in_the_rankings_own_order_as_a_percentile_and_is_public() -> None:
    harness = market()

    async with serve(harness, authorized=False) as client:
        answers = {
            stock_id: (await client.get(f"/v1/market/stocks/{stock_id}/ranking")).json() for stock_id in ("2330", "2317", "1101")
        }

    ranking = await harness.runtime.signed_out.load_ranking()
    assert [stock.stock_id for stock in ranking.stocks] == ["2330", "2317"]
    assert {stock_id: (answer["place"], answer["score"], answer["in_top"]) for stock_id, answer in answers.items()} == {
        "2330": (1, 100.0, True),
        "2317": (2, 50.0, True),
        "1101": (3, 0.0, False),
    }
    best = answers["2330"]
    assert (best["decided_on"], best["revenue_month"], best["universe"], best["scored"], best["formula"]["top"]) == (
        "2026-03-13",
        "2026-02-01",
        3,
        3,
        2,
    )
    assert (best["stock"]["factors"][0], best["exclusion"], best["holds_cash"]) == (
        {"value": pytest.approx(4 / 3), "rank": 1.0},
        None,
        False,
    )
    assert [factor["kind"] for factor in best["formula"]["factors"]] == ["revenue_acceleration", "nearness_to_high"]
    assert best["stock"]["stock_id"] == ranking.stocks[0].stock_id
    assert best["stock"]["score"] == ranking.stocks[0].score


async def test_a_stock_the_ranking_leaves_out_has_no_score_and_says_why() -> None:
    harness = market()
    harness.list_stock("0050", bars([100, 101, 102, 103, 104]))
    harness.list_stock("3008", bars([5, 5, 5, 5, 5]))
    harness.list_stock("2454", bars([100, 101, 102, 103, 104]))
    harness.list_stock("6547", [replace(bar, volume=1) for bar in bars([100, 101, 102, 103, 104])])
    harness.list_stock("6898", bars([100, 101, 102, 103, 104])[3:])

    for stock_id in ("0050", "3008", "6547", "6898"):
        for month in (1, 2):
            harness.archive.monthly_revenues[(stock_id, 2026, month)] = revenue(stock_id, 2026, month, 100.0)

    async with serve(harness, authorized=False) as client:
        answers = {
            stock_id: (await client.get(f"/v1/market/stocks/{stock_id}/ranking")).json()
            for stock_id in ("9999", "0050", "6898", "3008", "6547", "2454")
        }

    assert {stock_id: answer["exclusion"] for stock_id, answer in answers.items()} == {
        "9999": "no_history",
        "0050": "not_a_stock",
        "6898": "not_traded",
        "3008": "price_under_floor",
        "6547": "illiquid",
        "2454": "no_revenue_history",
    }
    assert {(answer["place"], answer["score"], answer["stock"], answer["in_top"]) for answer in answers.values()} == {
        (None, None, None, False)
    }


async def test_the_score_answers_ranking_unavailable_while_the_history_holds_no_decision_session() -> None:
    async with serve(build_harness(), authorized=False) as client:
        answer = await client.get("/v1/market/stocks/2330/ranking")

    assert (answer.status_code, answer.json().get("code")) == (422, "ranking_unavailable"), answer.text


async def test_a_backfill_holds_the_eps_pages_of_every_quarter_from_the_first_day() -> None:
    harness = build_harness()

    _, _, eps = await harness.runtime.signed_out.backfill_history(date(2025, 7, 1))

    assert eps == (5, 5)
    assert harness.fundamentals.requested == [
        {FiscalQuarter(2025, 3), FiscalQuarter(2025, 4), FiscalQuarter(2026, 1), FiscalQuarter(2026, 2), FiscalQuarter(2026, 3)}
    ]


class BoardSearch:
    """PTT's search page with one post dated 1/01 and one dated 12/31, as the board lists them without a year."""

    def __init__(self, **kwargs: object) -> None:
        pass

    async def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        rows = "".join(
            f'<div class="r-ent"><div class="title"><a href="/bbs/Stock/M.{post}.html">[標的] 2330 {day}</a></div>'
            f'<div class="date">{day}</div></div>'
            for post, day in ((1, " 1/01"), (2, "12/31"))
        )
        return httpx.Response(200, text=f"<html>{rows}</html>", request=httpx.Request("GET", url))


async def test_ptt_dates_its_posts_by_taipeis_day_on_a_server_in_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", BoardSearch)
    ptt = PttProvider(shipped_config(), SilentLogger(), StockDirectory(), MovableClock(NEW_YEARS_EVE_UTC.astimezone(TAIWAN_TIMEZONE)))

    posts = await ptt.fetch_stock_posts("2330", 10)

    assert [post.published_at.date() for post in posts] == [date(2027, 1, 1), date(2026, 12, 31)]
    assert all(post.published_at.utcoffset() == timedelta(hours=8) for post in posts)
    assert {(post.source, post.content, post.fetched_at) for post in posts} == {(InformationSource.PTT_STOCK, "", NEW_YEARS_EVE_UTC)}


async def test_a_ptt_search_that_fails_answers_no_post(monkeypatch: pytest.MonkeyPatch) -> None:
    class Down(BoardSearch):
        async def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
            raise httpx.ConnectError("PTT is down")

    monkeypatch.setattr(httpx, "AsyncClient", Down)
    ptt = PttProvider(shipped_config(), SilentLogger(), StockDirectory(), MovableClock(MARKET_OPEN))

    assert await ptt.fetch_stock_posts("2330", 10) == []


async def test_the_news_audit_file_is_dated_and_timed_in_taipei_on_a_server_in_utc(tmp_path: Path) -> None:
    clock = MovableClock(NEW_YEARS_EVE_UTC.astimezone(TAIWAN_TIMEZONE))
    provider = NewsProvider((), shipped_config(tmp_path), SilentLogger(), clock)

    provider.save_as_md_file("2330", [article("late news", InformationSource.NEWS_MEDIA, NEW_YEARS_EVE_UTC)])

    [saved] = (tmp_path / "news_archive" / "2027-01-01").glob("2330_003000.md")
    assert "**Published:** 2027-01-01 00:30" in saved.read_text(encoding="utf-8")


@pytest.mark.usefixtures("server_in_utc")
async def test_a_saved_ai_reply_is_named_by_taipeis_clock_on_a_server_in_utc(tmp_path: Path) -> None:
    before = datetime.now(TAIWAN_TIMEZONE).replace(microsecond=0)

    BaseAIAdapter(shipped_config(tmp_path), SilentLogger(), "a-model").save_response("2330", "{}")

    [saved] = (tmp_path / "ai_responses" / "2330").glob("report_*.md")
    named = datetime.strptime(saved.stem, "report_%Y%m%d_%H%M%S").replace(tzinfo=TAIWAN_TIMEZONE)
    assert before <= named <= datetime.now(TAIWAN_TIMEZONE)
