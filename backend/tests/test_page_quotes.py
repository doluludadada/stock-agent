"""
The realtime quotes the pages show (GET /v1/market/quotes): one board for every page and user, which asks the quote
source at a bounded rate whatever the number of open tabs, only around a session, and never on a site without quotes.
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from support.fakes import FakeMarketClock, RecordingLogger
from support.harness import MARKET_OPEN, MEMBER, MEMBER_PASSWORD, build_harness, harness_config
from support.settings import shipped_config
from support.web import app_of, client_at, serve, sign_in

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.types.enums import Audience, FeatureVisibility
from c_infrastructure.market import quote_board
from c_infrastructure.market.quote_board import QuoteBoard

pytestmark = pytest.mark.asyncio

MARKET_DATA = shipped_config().market_data
REFRESH = timedelta(seconds=MARKET_DATA.page_quote_refresh_seconds)
FIRST = timedelta(seconds=MARKET_DATA.page_quote_first_seconds)
IDLE = timedelta(seconds=MARKET_DATA.page_quote_idle_seconds)
CHANGING = {"changing": True, "seconds": MARKET_DATA.page_quote_refresh_seconds}
STOPPED = {"changing": False, "seconds": MARKET_DATA.page_quote_recheck_seconds}
TODAY = MARKET_OPEN.date()
CLOSE = MARKET_OPEN.replace(hour=13, minute=30)
QUOTES = "/v1/market/quotes"
PAGE_FEATURES = ("holdings", "mock_account", "ranking", "stock_pages", "watchlist")


class CountingQuotes:
    """A quote source that answers every stock at 100 and remembers each request; `failing` makes a request raise."""

    def __init__(self, clock: FakeMarketClock) -> None:
        self.clock = clock
        self.requests: list[tuple[datetime, list[str]]] = []
        self.failing = False

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        self.requests.append((self.clock.now(), [stock.stock_id for stock in stocks]))
        await asyncio.sleep(0)

        if self.failing:
            raise RuntimeError("Shioaji answered TimeoutError")

        return {stock.stock_id: quote(self.clock.now(), 100.0 + len(self.requests)) for stock in stocks}


def quote(at: datetime, price: float, change: float = 1.0) -> Ohlcv:
    return Ohlcv(ts=at, open=price, high=price, low=price, close=price, volume=5_000, change=change)


@pytest.fixture
def board(monkeypatch: pytest.MonkeyPatch) -> tuple[QuoteBoard, CountingQuotes, FakeMarketClock]:
    """A board over a counting source, whose wait for the next request moves the clock instead of taking the time."""
    clock = FakeMarketClock(now=MARKET_OPEN)
    source = CountingQuotes(clock)

    async def wait(seconds: float) -> None:
        clock.current_time += timedelta(seconds=seconds)

    monkeypatch.setattr(quote_board, "sleep", wait)
    return QuoteBoard(source, clock, MARKET_DATA, RecordingLogger()), source, clock


type Board = tuple[QuoteBoard, CountingQuotes, FakeMarketClock]


def most_in_any_window(requests: list[tuple[datetime, list[str]]], window: timedelta) -> int:
    times = [at for at, _ in requests]
    return max((sum(1 for other in times if at <= other < at + window) for at in times), default=0)


async def test_pages_that_ask_together_for_different_stocks_are_all_quoted_by_two_requests(board: Board) -> None:
    quotes, source, clock = board

    await asyncio.gather(*(quotes.follow([str(2300 + tab % 7), "2330"]) for tab in range(200)))

    assert [at for at, _ in source.requests] == [MARKET_OPEN, MARKET_OPEN + FIRST]
    assert quotes.quotes(["2330", "2303", "2306"], TODAY).keys() == {"2330", "2303", "2306"}


async def test_open_tabs_on_the_same_stocks_cost_one_request_per_refresh_interval_however_many_they_are(board: Board) -> None:
    quotes, source, clock = board
    step, minutes = timedelta(milliseconds=500), 10
    await asyncio.gather(*(quotes.follow(["2330", "2317", str(2300 + tab % 5)]) for tab in range(50)))
    source.requests.clear()

    for _ in range(minutes * 60 * 2):
        clock.current_time += step
        await asyncio.gather(*(quotes.follow(["2330", "2317", str(2300 + tab % 5)]) for tab in range(50)))

    assert len(source.requests) == minutes * 60 / REFRESH.total_seconds()
    assert most_in_any_window(source.requests, timedelta(seconds=10)) == 10 / REFRESH.total_seconds()


async def test_tabs_that_each_ask_for_a_stock_never_asked_before_cost_one_request_per_first_quote_interval(board: Board) -> None:
    quotes, source, clock = board

    for tick in range(300):
        await asyncio.gather(*(quotes.follow([f"N{tick}T{tab}"]) for tab in range(20)))
        clock.current_time += timedelta(milliseconds=100)

    times = [at for at, _ in source.requests]
    assert min(later - earlier for earlier, later in zip(times, times[1:], strict=False)) >= FIRST
    assert most_in_any_window(source.requests, timedelta(seconds=10)) <= 10 / FIRST.total_seconds()
    assert all(len(stock_ids) <= MARKET_DATA.quote_batch_size for _, stock_ids in source.requests)


async def test_a_request_asks_for_one_batch_of_the_stocks_asked_for_lately_and_drops_the_idle_ones(board: Board) -> None:
    quotes, source, clock = board
    many = [f"S{number}" for number in range(MARKET_DATA.quote_batch_size + 40)]

    await quotes.follow(many[:100])
    clock.current_time += REFRESH
    await quotes.follow(many[100:])

    assert len(source.requests[-1][1]) == MARKET_DATA.quote_batch_size
    assert set(many[100:]) <= set(source.requests[-1][1])

    clock.current_time += IDLE + REFRESH
    await quotes.follow(["2330"])

    assert source.requests[-1][1] == ["2330"]
    assert quotes.quotes(many, TODAY) == {}


async def test_a_known_stock_waits_for_the_refresh_and_a_new_one_only_for_the_first_quote_interval(board: Board) -> None:
    quotes, source, clock = board
    await quotes.follow(["2330"])

    clock.current_time += REFRESH - timedelta(seconds=1)
    await quotes.follow(["2330"])
    assert len(source.requests) == 1

    await quotes.follow(["2330", "2454"])
    assert len(source.requests) == 2 and set(source.requests[-1][1]) == {"2330", "2454"}
    assert clock.now() == MARKET_OPEN + REFRESH - timedelta(seconds=1)

    await quotes.follow(["2603"])
    assert source.requests[-1][0] == MARKET_OPEN + REFRESH - timedelta(seconds=1) + FIRST


async def test_a_failed_request_keeps_the_quotes_held_and_is_not_made_again_before_the_refresh_interval(board: Board) -> None:
    quotes, source, clock = board
    await quotes.follow(["2330"])
    held = quotes.quotes(["2330"], TODAY)
    source.failing = True

    for _ in range(int(REFRESH / FIRST) + 1):
        clock.current_time += FIRST
        await quotes.follow(["2330", "2454"])

    assert len(source.requests) == 3
    assert quotes.quotes(["2330", "2454"], TODAY) == held
    assert quotes.read_at() == source.requests[0][0]


async def test_the_board_answers_only_the_quotes_traded_in_the_session_asked_for(board: Board) -> None:
    quotes, _, clock = board
    await quotes.follow(["2330"])

    assert quotes.quotes(["2330"], TODAY).keys() == {"2330"}
    assert quotes.quotes(["2330"], TODAY + timedelta(days=1)) == {}


async def test_a_page_that_asks_for_more_stocks_than_one_request_reads_is_followed_for_the_first_ones(board: Board) -> None:
    quotes, source, clock = board
    many = [f"S{number}" for number in range(MARKET_DATA.quote_batch_size + 40)]

    for _ in range(3):
        await quotes.follow(many)
        clock.current_time += FIRST

    assert [stock_ids for _, stock_ids in source.requests] == [many[: MARKET_DATA.quote_batch_size]]


def site(now: datetime = MARKET_OPEN, **changes):
    harness = build_harness(now=now, **changes)
    harness.prices.realtime["2330"] = quote(now - timedelta(seconds=3), 1_000.0, change=-5.0)
    return harness


async def test_in_session_the_endpoint_answers_the_quote_and_asks_the_source_once_per_refresh_interval() -> None:
    harness = site()

    async with serve(harness) as client:
        first = (await client.get(QUOTES, params={"ids": ["2330", "2317"]})).json()
        again = (await client.get(QUOTES, params={"ids": ["2330", "2317"]})).json()
        harness.clock.current_time += REFRESH
        harness.prices.realtime["2330"] = quote(harness.clock.now(), 1_005.0, change=0.0)
        later = (await client.get(QUOTES, params={"ids": ["2330", "2317"]})).json()

    assert first == again
    assert first["realtime_quotes"] is True and first["refresh"] == CHANGING
    assert first["quotes"]["2317"] is None
    assert {key: first["quotes"]["2330"][key] for key in ("close", "change", "volume")} == {
        "close": 1_000.0,
        "change": -5.0,
        "volume": 5_000,
    }
    assert first["quotes"]["2330"]["ts"] == (MARKET_OPEN - timedelta(seconds=3)).isoformat()
    assert later["quotes"]["2330"]["close"] == 1_005.0
    assert harness.prices.realtime_requests == ["2330", "2317"] * 2
    assert harness.journal.runs == {} and harness.journal.orders == {}


async def test_after_the_close_the_source_is_asked_once_more_and_then_the_last_quotes_are_only_read() -> None:
    harness = site()

    async with serve(harness) as client:
        await client.get(QUOTES, params={"ids": ["2330"]})
        harness.clock.current_time = CLOSE + timedelta(seconds=20)
        harness.prices.realtime["2330"] = quote(CLOSE, 1_010.0)
        closing = (await client.get(QUOTES, params={"ids": ["2330"]})).json()
        harness.clock.current_time += timedelta(hours=2)
        evening = (await client.get(QUOTES, params={"ids": ["2330", "2454"]})).json()

    assert closing["refresh"] == CHANGING and closing["quotes"]["2330"]["close"] == 1_010.0
    assert evening["refresh"] == STOPPED
    assert evening["quotes"] == {"2330": closing["quotes"]["2330"], "2454": None}
    assert harness.prices.realtime_requests == ["2330", "2330"]


async def test_a_request_after_the_close_that_fails_is_made_again_at_the_boards_pace_until_one_is_answered() -> None:
    harness = site()
    asked = harness.prices.fetch_realtime_bars

    async def refused(stocks: list[Stock]) -> dict[str, Ohlcv]:
        await asked(stocks)
        raise RuntimeError("Shioaji answered TimeoutError")

    async with serve(harness) as client:
        await client.get(QUOTES, params={"ids": ["2330"]})
        harness.clock.current_time = CLOSE + timedelta(seconds=20)
        harness.prices.realtime["2330"] = quote(CLOSE, 1_010.0)
        harness.prices.fetch_realtime_bars = refused
        failed = (await client.get(QUOTES, params={"ids": ["2330"]})).json()
        too_soon = (await client.get(QUOTES, params={"ids": ["2330"]})).json()
        harness.clock.current_time += REFRESH
        harness.prices.fetch_realtime_bars = asked
        answered = (await client.get(QUOTES, params={"ids": ["2330"]})).json()
        harness.clock.current_time += REFRESH
        after = (await client.get(QUOTES, params={"ids": ["2330"]})).json()

    assert failed["refresh"] == too_soon["refresh"] == CHANGING and failed["quotes"]["2330"]["close"] == 1_000.0
    assert answered["refresh"] == CHANGING and answered["quotes"]["2330"]["close"] == 1_010.0
    assert after["refresh"] == STOPPED and after["quotes"] == answered["quotes"]
    assert harness.prices.realtime_requests == ["2330"] * 3


@pytest.mark.parametrize(
    "now",
    [MARKET_OPEN.replace(hour=8, minute=0), MARKET_OPEN + timedelta(days=5), MARKET_OPEN + timedelta(days=5, hours=8)],
    ids=["before the open", "Saturday morning", "Saturday evening"],
)
async def test_outside_a_session_with_nothing_held_the_source_is_not_asked(now: datetime) -> None:
    harness = site(now)

    async with serve(harness) as client:
        answer = (await client.get(QUOTES, params={"ids": ["2330"]})).json()

    assert answer == {"realtime_quotes": True, "refresh": STOPPED, "quotes": {"2330": None}}
    assert harness.prices.realtime_requests == []


async def test_a_quote_of_an_earlier_session_is_not_answered_the_next_day() -> None:
    harness = site()

    async with serve(harness) as client:
        await client.get(QUOTES, params={"ids": ["2330"]})
        harness.clock.current_time = MARKET_OPEN + timedelta(days=1, hours=-2)
        next_morning = (await client.get(QUOTES, params={"ids": ["2330"]})).json()

    assert next_morning["refresh"] == STOPPED and next_morning["quotes"] == {"2330": None}
    assert harness.prices.realtime_requests == ["2330"]


@pytest.mark.parametrize(
    "changes",
    [{"realtime_quotes": False}, {"config": harness_config().model_copy(update={"audience": Audience.PUBLIC})}],
    ids=["a personal site without a Shioaji login", "a public site"],
)
async def test_a_site_without_realtime_quotes_says_so_and_asks_nothing(changes: dict) -> None:
    harness = site(**changes)

    async with serve(harness) as client:
        response = await client.get(QUOTES, params={"ids": ["2330"]})

    assert response.status_code == 200
    assert response.json() == {"realtime_quotes": False, "refresh": None, "quotes": {"2330": None}}
    assert harness.prices.realtime_requests == []


async def test_a_login_that_went_down_stops_the_requests_of_the_source() -> None:
    harness = site()

    async with serve(harness) as client:
        harness.dependencies.shioaji.up = False
        answer = (await client.get(QUOTES, params={"ids": ["2330"]})).json()

    assert answer["realtime_quotes"] is False and answer["quotes"] == {"2330": None}
    assert harness.prices.realtime_requests == []


async def test_a_visitor_is_refused_and_a_user_needs_one_of_the_pages_that_show_quotes() -> None:
    config = harness_config()
    hidden = config.features.model_copy(update=dict.fromkeys(PAGE_FEATURES, FeatureVisibility.ADMINISTRATORS))
    one_shown = hidden.model_copy(update={"watchlist": FeatureVisibility.EVERYONE})
    answers = []

    for features in (hidden, one_shown):
        harness = site(config=config.model_copy(update={"features": features}))
        harness.users.add(MEMBER, MEMBER_PASSWORD)

        async with app_of(harness) as app, client_at(app) as visitor, client_at(app) as member:
            await sign_in(member, MEMBER.username, MEMBER_PASSWORD)
            signed_out = await visitor.get(QUOTES, params={"ids": ["2330"]})
            answer = await member.get(QUOTES, params={"ids": ["2330"]})

        answers.append((signed_out.status_code, answer.status_code, answer.json().get("code"), len(harness.prices.realtime_requests)))

    assert answers == [(401, 403, "feature_hidden", 0), (401, 200, None, 1)]


@pytest.mark.parametrize("ids", [[], ["2330;drop"], ["12345678901"]], ids=["none", "not a stock id", "too long"])
async def test_the_endpoint_refuses_a_request_that_names_no_stock_or_no_stock_id(ids: list[str]) -> None:
    harness = site()

    async with serve(harness) as client:
        refused = await client.get(QUOTES, params={"ids": ids})

    assert refused.status_code == 422
    assert harness.prices.realtime_requests == []


async def test_the_endpoint_reads_the_first_stocks_of_a_request_that_names_more_than_the_board_reads_at_once() -> None:
    config = harness_config()
    harness = site(config=config.model_copy(update={"market_data": config.market_data.model_copy(update={"quote_batch_size": 2})}))
    harness.prices.realtime |= {stock_id: quote(MARKET_OPEN, 50.0) for stock_id in ("2317", "2454")}

    async with serve(harness) as client:
        answer = (await client.get(QUOTES, params={"ids": ["2330", "2317", "2454"]})).json()

    assert harness.prices.realtime_requests == ["2330", "2317"]
    assert [stock_id for stock_id, held in answer["quotes"].items() if held is None] == ["2454"]
