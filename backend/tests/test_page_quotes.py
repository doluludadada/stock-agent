"""
The realtime quotes the pages show (GET /v1/market/quotes): one board for every page and user, which asks the quote
source at a bounded rate whatever the number of open tabs, only around a session, and never on a site without quotes.
The market overview's index (GET /v1/market/index-quotes) is a request of its own, of the broker's market data, paced
like the stocks' and apart from them.
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
from a_domain.types.enums import Audience, FeatureVisibility, MarketIndex
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
INDEX_QUOTES = "/v1/market/index-quotes"
TAIEX = {"indexes": ["taiex"]}
SHIOAJI_WINDOW = timedelta(seconds=10)
"""Shioaji counts its 50 market-data queries per 10 seconds on one login."""
PAGE_FEATURES = ("holdings", "mock_account", "ranking", "stock_pages", "watchlist")


class CountingQuotes:
    """
    A quote source that answers every stock at 100 and every index at 40,000 and remembers each request; `failing`
    makes a request of the stocks raise and `index_failing` one of the indexes.
    """

    def __init__(self, clock: FakeMarketClock) -> None:
        self.clock = clock
        self.requests: list[tuple[datetime, list[str]]] = []
        self.index_requests: list[tuple[datetime, list[MarketIndex]]] = []
        self.failing = False
        self.index_failing = False

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        self.requests.append((self.clock.now(), [stock.stock_id for stock in stocks]))
        await asyncio.sleep(0)

        if self.failing:
            raise RuntimeError("Shioaji answered TimeoutError")

        return {stock.stock_id: quote(self.clock.now(), 100.0 + len(self.requests)) for stock in stocks}

    async def fetch_index_quotes(self, indexes: list[MarketIndex]) -> dict[MarketIndex, Ohlcv]:
        self.index_requests.append((self.clock.now(), list(indexes)))
        await asyncio.sleep(0)

        if self.index_failing:
            raise RuntimeError("Shioaji answered TimeoutError")

        return {index: quote(self.clock.now(), 40_000.0 + len(self.index_requests), change=-12.5) for index in indexes}


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
    return QuoteBoard(source, source, clock, MARKET_DATA, RecordingLogger()), source, clock


type Board = tuple[QuoteBoard, CountingQuotes, FakeMarketClock]


def most_in_any_window(requests: list[tuple[datetime, list]], window: timedelta) -> int:
    times = [at for at, _ in requests]
    return max((sum(1 for other in times if at <= other < at + window) for at in times), default=0)


async def test_pages_that_ask_together_for_different_stocks_are_all_quoted_by_two_requests(board: Board) -> None:
    quotes, source, clock = board

    await asyncio.gather(*(quotes.follow([str(2300 + tab % 7), "2330"], []) for tab in range(200)))

    assert [at for at, _ in source.requests] == [MARKET_OPEN, MARKET_OPEN + FIRST]
    assert quotes.quotes(["2330", "2303", "2306"], TODAY).keys() == {"2330", "2303", "2306"}


async def test_open_tabs_on_the_same_stocks_cost_one_request_per_refresh_interval_however_many_they_are(board: Board) -> None:
    quotes, source, clock = board
    step, minutes = timedelta(milliseconds=500), 10
    await asyncio.gather(*(quotes.follow(["2330", "2317", str(2300 + tab % 5)], []) for tab in range(50)))
    source.requests.clear()

    for _ in range(minutes * 60 * 2):
        clock.current_time += step
        await asyncio.gather(*(quotes.follow(["2330", "2317", str(2300 + tab % 5)], []) for tab in range(50)))

    assert len(source.requests) == minutes * 60 / REFRESH.total_seconds()
    assert most_in_any_window(source.requests, timedelta(seconds=10)) == 10 / REFRESH.total_seconds()


async def test_tabs_that_each_ask_for_a_stock_never_asked_before_cost_one_request_per_first_quote_interval(board: Board) -> None:
    quotes, source, clock = board

    for tick in range(300):
        await asyncio.gather(*(quotes.follow([f"N{tick}T{tab}"], []) for tab in range(20)))
        clock.current_time += timedelta(milliseconds=100)

    times = [at for at, _ in source.requests]
    assert min(later - earlier for earlier, later in zip(times, times[1:], strict=False)) >= FIRST
    assert most_in_any_window(source.requests, timedelta(seconds=10)) <= 10 / FIRST.total_seconds()
    assert all(len(stock_ids) <= MARKET_DATA.quote_batch_size for _, stock_ids in source.requests)


async def test_a_request_asks_for_one_batch_of_the_stocks_asked_for_lately_and_drops_the_idle_ones(board: Board) -> None:
    quotes, source, clock = board
    many = [f"S{number}" for number in range(MARKET_DATA.quote_batch_size + 40)]

    await quotes.follow(many[:100], [])
    clock.current_time += REFRESH
    await quotes.follow(many[100:], [])

    assert len(source.requests[-1][1]) == MARKET_DATA.quote_batch_size
    assert set(many[100:]) <= set(source.requests[-1][1])

    clock.current_time += IDLE + REFRESH
    await quotes.follow(["2330"], [])

    assert source.requests[-1][1] == ["2330"]
    assert quotes.quotes(many, TODAY) == {}


async def test_a_known_stock_waits_for_the_refresh_and_a_new_one_only_for_the_first_quote_interval(board: Board) -> None:
    quotes, source, clock = board
    await quotes.follow(["2330"], [])

    clock.current_time += REFRESH - timedelta(seconds=1)
    await quotes.follow(["2330"], [])
    assert len(source.requests) == 1

    await quotes.follow(["2330", "2454"], [])
    assert len(source.requests) == 2 and set(source.requests[-1][1]) == {"2330", "2454"}
    assert clock.now() == MARKET_OPEN + REFRESH - timedelta(seconds=1)

    await quotes.follow(["2603"], [])
    assert source.requests[-1][0] == MARKET_OPEN + REFRESH - timedelta(seconds=1) + FIRST


async def test_a_failed_request_keeps_the_quotes_held_and_is_not_made_again_before_the_refresh_interval(board: Board) -> None:
    quotes, source, clock = board
    await quotes.follow(["2330"], [])
    held = quotes.quotes(["2330"], TODAY)
    source.failing = True

    for _ in range(int(REFRESH / FIRST) + 1):
        clock.current_time += FIRST
        await quotes.follow(["2330", "2454"], [])

    assert len(source.requests) == 3
    assert quotes.quotes(["2330", "2454"], TODAY) == held
    assert quotes.read_at(["2330"], []) == source.requests[0][0]


async def test_the_board_answers_only_the_quotes_traded_in_the_session_asked_for(board: Board) -> None:
    quotes, _, clock = board
    await quotes.follow(["2330"], [])

    assert quotes.quotes(["2330"], TODAY).keys() == {"2330"}
    assert quotes.quotes(["2330"], TODAY + timedelta(days=1)) == {}


async def test_a_page_that_asks_for_more_stocks_than_one_request_reads_is_followed_for_the_first_ones(board: Board) -> None:
    quotes, source, clock = board
    many = [f"S{number}" for number in range(MARKET_DATA.quote_batch_size + 40)]

    for _ in range(3):
        await quotes.follow(many, [])
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

    assert answer == {"realtime_quotes": True, "refresh": STOPPED, "quotes": {"2330": None}, "indexes": {}}
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
    assert response.json() == {"realtime_quotes": False, "refresh": None, "quotes": {"2330": None}, "indexes": {}}
    assert harness.prices.realtime_requests == []


async def test_a_login_that_went_down_stops_the_requests_of_the_source() -> None:
    harness = site()

    async with serve(harness) as client:
        harness.dependencies.shioaji.lost(harness.dependencies.shioaji.client)
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


async def test_the_indexes_are_one_request_of_their_own_paced_apart_from_the_stocks(board: Board) -> None:
    quotes, source, clock = board

    await asyncio.gather(*(quotes.follow(["2330"], [MarketIndex.TAIEX]) for _ in range(50)), quotes.follow(["2317"], []))

    assert [at for at, _ in source.requests] == [MARKET_OPEN, MARKET_OPEN + FIRST]
    assert source.index_requests == [(MARKET_OPEN, [MarketIndex.TAIEX])]
    assert [sorted(stock_ids) for _, stock_ids in source.requests] == [["2330"], ["2317", "2330"]]
    assert quotes.index_quotes([MarketIndex.TAIEX], TODAY)[MarketIndex.TAIEX].change == -12.5
    assert quotes.index_quotes([MarketIndex.TAIEX], TODAY + timedelta(days=1)) == {}
    assert quotes.quotes(["taiex"], TODAY) == {}


async def test_stocks_asked_alone_cost_the_broker_no_index_request_and_an_index_waits_for_no_stock_request(board: Board) -> None:
    quotes, source, clock = board

    for _ in range(3):
        await quotes.follow(["2330"], [])
        clock.current_time += timedelta(seconds=1)

    await quotes.follow([], [MarketIndex.TAIEX])

    assert len(source.requests) == 1 and source.index_requests == [(clock.now(), [MarketIndex.TAIEX])]


async def test_an_index_request_that_fails_costs_the_stocks_nothing_and_is_made_again_no_sooner_than_the_refresh(board: Board) -> None:
    quotes, source, clock = board
    source.index_failing = True

    for _ in range(4):
        await quotes.follow(["2330"], [MarketIndex.TAIEX])
        clock.current_time += REFRESH / 2

    assert quotes.quotes(["2330"], TODAY)["2330"].close == 102.0
    assert quotes.read_at(["2330"], []) == MARKET_OPEN + REFRESH
    assert quotes.index_quotes([MarketIndex.TAIEX], TODAY) == {} and quotes.read_at([], [MarketIndex.TAIEX]) is None
    assert quotes.read_at(["2330"], [MarketIndex.TAIEX]) is None
    assert [at for at, _ in source.index_requests] == [MARKET_OPEN, MARKET_OPEN + REFRESH]
    assert [at for at, _ in source.requests] == [MARKET_OPEN, MARKET_OPEN + REFRESH]

    source.index_failing = False
    await quotes.follow(["2330"], [MarketIndex.TAIEX])
    assert quotes.index_quotes([MarketIndex.TAIEX], TODAY)[MarketIndex.TAIEX].close == 40_003.0
    assert quotes.read_at([], [MarketIndex.TAIEX]) == MARKET_OPEN + 2 * REFRESH


async def test_a_stock_request_that_fails_leaves_the_index_its_quote(board: Board) -> None:
    quotes, source, clock = board
    source.failing = True

    await quotes.follow(["2330"], [MarketIndex.TAIEX])

    assert quotes.quotes(["2330"], TODAY) == {} and quotes.read_at(["2330"], []) is None
    assert quotes.index_quotes([MarketIndex.TAIEX], TODAY)[MarketIndex.TAIEX].close == 40_001.0


async def test_a_tab_on_the_market_overview_costs_one_index_request_per_refresh_interval_and_a_session_1620(board: Board) -> None:
    quotes, source, clock = board
    session = CLOSE - MARKET_OPEN.replace(hour=9, minute=0)
    clock.current_time = MARKET_OPEN.replace(hour=9, minute=0)

    while clock.now() < CLOSE:
        await asyncio.gather(*(quotes.follow([], [MarketIndex.TAIEX]) for _ in range(20)))
        clock.current_time += REFRESH / 4

    assert len(source.index_requests) == session / REFRESH == 1_620
    assert most_in_any_window(source.index_requests, SHIOAJI_WINDOW) == 1
    assert source.requests == []


async def test_an_index_request_that_hangs_holds_no_stock_page(board: Board) -> None:
    quotes, source, clock = board
    answered = asyncio.Event()

    async def hanging(indexes: list[MarketIndex]) -> dict[MarketIndex, Ohlcv]:
        source.index_requests.append((clock.now(), list(indexes)))
        await answered.wait()
        return {}

    source.fetch_index_quotes = hanging
    overview_tab = asyncio.create_task(quotes.follow([], [MarketIndex.TAIEX]))
    await asyncio.sleep(0)

    await asyncio.wait_for(quotes.follow(["2330"], []), timeout=1)

    assert quotes.quotes(["2330"], TODAY).keys() == {"2330"} and len(source.index_requests) == 1
    answered.set()
    await overview_tab


async def test_tabs_on_the_market_overview_and_on_new_stocks_cost_at_most_two_requests_per_first_quote_interval(board: Board) -> None:
    quotes, source, clock = board

    for second in range(60):
        await asyncio.gather(quotes.follow([f"N{second}"], []), *(quotes.follow([], [MarketIndex.TAIEX]) for _ in range(20)))
        clock.current_time += timedelta(seconds=1)

    most = most_in_any_window([*source.requests, *source.index_requests], SHIOAJI_WINDOW)
    assert most <= 2 * SHIOAJI_WINDOW / FIRST == 10


def overview(now: datetime = MARKET_OPEN, **changes):
    """A site whose broker answers the TAIEX at 41,000, stamped a few seconds before `now`."""
    harness = site(now, **changes)
    harness.prices.index_quotes[MarketIndex.TAIEX] = quote(now - timedelta(seconds=5), 41_000.0, change=-40.08)
    return harness


async def test_in_session_the_index_is_answered_at_its_quote_and_asked_once_per_refresh_interval() -> None:
    harness = overview()

    async with serve(harness) as client:
        first = (await client.get(INDEX_QUOTES, params=TAIEX)).json()
        again = (await client.get(INDEX_QUOTES, params=TAIEX)).json()
        harness.clock.current_time += REFRESH
        harness.prices.index_quotes[MarketIndex.TAIEX] = quote(harness.clock.now(), 41_050.0, change=9.92)
        later = (await client.get(INDEX_QUOTES, params=TAIEX)).json()

    index = first["indexes"]["taiex"]
    assert (index["close"], index["change"], index["ts"]) == (41_000.0, -40.08, (MARKET_OPEN - timedelta(seconds=5)).isoformat())
    assert first == again and first["refresh"] == CHANGING and first["quotes"] == {}
    assert later["indexes"]["taiex"]["close"] == 41_050.0
    assert harness.prices.index_requests == [[MarketIndex.TAIEX]] * 2 and harness.prices.realtime_requests == []
    assert harness.journal.runs == {} and harness.journal.orders == {}


async def test_in_the_opening_call_auction_the_index_is_asked_and_answered_once_the_broker_has_a_value_of_the_session() -> None:
    harness = site(MARKET_OPEN.replace(hour=8, minute=45))

    async with serve(harness) as client:
        before = (await client.get(INDEX_QUOTES, params=TAIEX)).json()
        harness.clock.current_time = MARKET_OPEN.replace(hour=9, minute=0, second=5)
        harness.prices.index_quotes[MarketIndex.TAIEX] = quote(harness.clock.now(), 41_000.0)
        opened = (await client.get(INDEX_QUOTES, params=TAIEX)).json()

    assert before == {"realtime_quotes": True, "refresh": CHANGING, "quotes": {}, "indexes": {"taiex": None}}
    assert opened["refresh"] == CHANGING and opened["indexes"]["taiex"]["close"] == 41_000.0
    assert harness.prices.index_requests == [[MarketIndex.TAIEX]] * 2


async def test_after_the_close_the_index_is_read_once_more_and_then_only_answered() -> None:
    harness = overview()

    async with serve(harness) as client:
        await client.get(INDEX_QUOTES, params=TAIEX)
        harness.clock.current_time = CLOSE + timedelta(seconds=20)
        harness.prices.index_quotes[MarketIndex.TAIEX] = quote(CLOSE, 41_100.0, change=59.92)
        closing = (await client.get(INDEX_QUOTES, params=TAIEX)).json()
        harness.clock.current_time += timedelta(hours=2)
        evening = (await client.get(INDEX_QUOTES, params=TAIEX)).json()

    assert closing["refresh"] == CHANGING and closing["indexes"]["taiex"]["close"] == 41_100.0
    assert evening["refresh"] == STOPPED and evening["indexes"] == closing["indexes"]
    assert harness.prices.index_requests == [[MarketIndex.TAIEX]] * 2


async def test_after_the_close_an_index_that_fails_keeps_no_stock_page_asking() -> None:
    harness = overview()

    async def refused(indexes: list[MarketIndex]) -> dict[MarketIndex, Ohlcv]:
        harness.prices.index_requests.append(list(indexes))
        raise RuntimeError("Shioaji answered TimeoutError")

    async with serve(harness) as client:
        await client.get(INDEX_QUOTES, params=TAIEX)
        await client.get(QUOTES, params={"ids": ["2330"]})
        harness.clock.current_time = CLOSE + timedelta(seconds=20)
        harness.prices.realtime["2330"] = quote(CLOSE, 1_010.0)
        harness.prices.fetch_index_quotes = refused
        index_closing = (await client.get(INDEX_QUOTES, params=TAIEX)).json()
        closing = (await client.get(QUOTES, params={"ids": ["2330"]})).json()
        harness.clock.current_time += REFRESH
        evening = (await client.get(QUOTES, params={"ids": ["2330"]})).json()
        index_evening = (await client.get(INDEX_QUOTES, params=TAIEX)).json()

    assert closing["quotes"]["2330"]["close"] == 1_010.0 and evening["refresh"] == STOPPED
    assert index_closing["refresh"] == index_evening["refresh"] == CHANGING
    assert harness.prices.realtime_requests == ["2330", "2330"] and len(harness.prices.index_requests) == 3


@pytest.mark.parametrize(
    "now", [MARKET_OPEN.replace(hour=8, minute=0), MARKET_OPEN + timedelta(days=5)], ids=["before the open", "Saturday morning"]
)
async def test_outside_a_session_the_index_is_answered_nothing_and_the_source_is_not_asked(now: datetime) -> None:
    harness = overview(now)

    async with serve(harness) as client:
        answer = (await client.get(INDEX_QUOTES, params=TAIEX)).json()

    assert answer == {"realtime_quotes": True, "refresh": STOPPED, "quotes": {}, "indexes": {"taiex": None}}
    assert harness.prices.index_requests == []


@pytest.mark.parametrize(
    "changes",
    [{"realtime_quotes": False}, {"config": harness_config().model_copy(update={"audience": Audience.PUBLIC})}],
    ids=["a personal site without a Shioaji login", "a public site"],
)
async def test_a_site_without_realtime_quotes_answers_no_index_and_asks_nothing(changes: dict) -> None:
    harness = overview(**changes)

    async with serve(harness) as client:
        answer = (await client.get(INDEX_QUOTES, params=TAIEX)).json()

    assert answer == {"realtime_quotes": False, "refresh": None, "quotes": {}, "indexes": {"taiex": None}}
    assert harness.prices.index_requests == []


@pytest.mark.parametrize(
    ("shown", "expected"),
    [("market_overview", (200, 403)), ("watchlist", (403, 200)), (None, (403, 403))],
    ids=["shown the market overview alone", "shown the watchlist alone", "shown neither"],
)
async def test_the_index_needs_the_market_overview_and_a_stocks_quote_one_of_the_pages_that_show_it(
    shown: str | None, expected: tuple[int, int]
) -> None:
    config = harness_config()
    features = config.features.model_copy(update=dict.fromkeys((*PAGE_FEATURES, "market_overview"), FeatureVisibility.ADMINISTRATORS))
    features = features.model_copy(update={shown: FeatureVisibility.EVERYONE} if shown else {})
    harness = overview(config=config.model_copy(update={"features": features}))
    harness.users.add(MEMBER, MEMBER_PASSWORD)

    async with app_of(harness) as app, client_at(app) as visitor, client_at(app) as member:
        await sign_in(member, MEMBER.username, MEMBER_PASSWORD)
        signed_out = await visitor.get(INDEX_QUOTES, params=TAIEX)
        answers = (await member.get(INDEX_QUOTES, params=TAIEX), await member.get(QUOTES, params={"ids": ["2330"]}))

    assert signed_out.status_code == 401
    assert tuple(answer.status_code for answer in answers) == expected
    assert len(harness.prices.index_requests) == (expected[0] == 200) and len(harness.prices.realtime_requests) == (expected[1] == 200)


@pytest.mark.parametrize(
    ("path", "params"),
    [(INDEX_QUOTES, {"indexes": ["tpex"]}), (INDEX_QUOTES, {}), (QUOTES, TAIEX)],
    ids=["not a market index", "no index", "indexes of the stock route"],
)
async def test_each_route_refuses_a_request_that_names_nothing_it_quotes(path: str, params: dict) -> None:
    harness = overview()

    async with serve(harness) as client:
        refused = await client.get(path, params=params)

    assert refused.status_code == 422
    assert harness.prices.realtime_requests == [] and harness.prices.index_requests == []
