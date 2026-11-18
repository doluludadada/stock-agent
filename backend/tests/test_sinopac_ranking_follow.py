"""
A ranking follow on SinoPac, the user's follow account: by hand (`POST /v1/rankings/follow`) or by their schedule, it brings
SinoPac's account to the ranking through the order path every SinoPac order takes, and only while the login that
answers is on SinoPac's simulation server. A production login is refused when the run starts, before the account is
read, at each order's preparation and right before each exchange order, whatever the settings. Only an active
administrator the site lets order on SinoPac is followed there, and one who loses any of that is refused and followed on
no account, never on the mock account in its place.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import uuid4

import httpx
import pytest
from support.fakes import FakeMarketClock, FakeOrderingSwitch, FakeTradingJournal, FakeUserStore, RecordingExecutionProvider
from support.harness import ADMINISTRATOR, ADMINISTRATOR_PASSWORD, MEMBER, MEMBER_PASSWORD, CliHarness, harness_config
from support.web import app_of, client_at, ended, sign_in, write
from test_follow_schedule import NINE_FIVE, RULE, at, finished, follow, look, weekdays
from test_ranking_follow import CLOSES, FORMULA, affordable, site
from trading_stack import SilentLogger, bar, run_stats

from a_domain.model.market.stock import Stock
from a_domain.model.system.user import User
from a_domain.model.trading.account import Account, Position
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.trading.follow import FollowAccount
from a_domain.rules.trading.order_rule import BrokerLink, SimulationOnlyRule, SiteOrdering
from a_domain.rules.trading.ranking import RankedFactor, RankedStock, Ranking
from a_domain.types.enums import (
    ExecutionProvider,
    FeatureVisibility,
    FollowAccountRefusal,
    OrderStatus,
    OrderType,
    RejectReason,
    Role,
    ShioajiServer,
    TimeInForce,
    TradeAction,
    TradingPhase,
    UserStatus,
    Workflow,
)
from a_domain.types.errors import FollowAccountChanged
from a_domain.types.ids import RunId, UserId
from b_application.use_cases.trade.order_execution import OrderExecution

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
SIMULATION = BrokerLink(broker=ExecutionProvider.SHIOAJI, up=True, simulation=True)
PRODUCTION = BrokerLink(broker=ExecutionProvider.SHIOAJI, up=True, simulation=False)
MOCK = BrokerLink(broker=ExecutionProvider.MOCK)
ADMIN = User(user_id=UserId("u-admin"), username="admin", email="admin@example.com", role=Role.ADMINISTRATOR, created_at=NOW)
PLAIN = replace(ADMIN, user_id=UserId("u-plain"), role=Role.USER)


def sinopac_shown(visibility: FeatureVisibility) -> SiteOrdering:
    """Settings files on disk on SinoPac's simulation server that show `visibility` ordering on SinoPac and everyone on the mock."""
    ordering = {ExecutionProvider.MOCK: FeatureVisibility.EVERYONE, ExecutionProvider.SHIOAJI: visibility}
    return SiteOrdering(ordering=ordering, server=ShioajiServer.SIMULATION)


SHOWN = sinopac_shown(FeatureVisibility.ADMINISTRATORS)
OFF = sinopac_shown(FeatureVisibility.OFF)
EVERYONE = sinopac_shown(FeatureVisibility.EVERYONE)


def order_of(action: TradeAction = TradeAction.BUY) -> Order:
    return Order(
        run_id=RunId(uuid4()),
        decision_id=uuid4(),
        stock_id="2330",
        action=action,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.IOC,
        quantity=100,
        limit_price=100.0,
        created_at=NOW,
        updated_at=NOW,
    )


def reason_of(refusal: tuple[RejectReason, str] | None) -> RejectReason | None:
    return refusal[0] if refusal is not None else None


# ----------------------------------- Rules ------------------------------------ #


def test_only_a_ranking_follow_on_a_real_broker_off_its_simulation_server_is_refused_as_not_simulation() -> None:
    rule = SimulationOnlyRule()
    unknown_server = replace(SIMULATION, simulation=None)

    refused = {
        (workflow, link.simulation): reason_of(rule.apply(workflow, link))
        for workflow in (Workflow.RANKING_FOLLOW, Workflow.MANUAL_BUY, Workflow.BUZZ_SCAN, Workflow.INTRADAY)
        for link in (SIMULATION, PRODUCTION, unknown_server)
    }

    assert {key for key, reason in refused.items() if reason is not None} == {
        (Workflow.RANKING_FOLLOW, False),
        (Workflow.RANKING_FOLLOW, None),
    }
    assert set(refused.values()) == {None, RejectReason.NOT_SIMULATION}
    assert rule.apply(Workflow.RANKING_FOLLOW, MOCK) is None
    assert [workflow for workflow in Workflow if workflow.simulation_only] == [Workflow.RANKING_FOLLOW]


@pytest.mark.parametrize("server", list(ShioajiServer))
async def test_no_setting_lets_a_ranking_follows_order_reach_a_production_login(server: ShioajiServer) -> None:
    """
    With the settings on disk naming production the login rule takes the production login and the switch and the user
    allow the order: the workflow alone refuses it.
    """
    rule, on_disk = harness_config().broker_access_rule(), replace(EVERYONE, server=server)

    def refusal(workflow: Workflow, link: BrokerLink) -> RejectReason | None:
        return reason_of(rule.apply(order_of(), workflow, ExecutionProvider.SHIOAJI, link, ADMIN, on_disk, []))

    on_production = not server.simulation
    assert refusal(Workflow.RANKING_FOLLOW, PRODUCTION) == RejectReason.NOT_SIMULATION
    assert refusal(Workflow.RANKING_FOLLOW, SIMULATION) == (RejectReason.BROKER_SERVER_MISMATCH if on_production else None)
    assert refusal(Workflow.MANUAL_BUY, PRODUCTION) == (None if on_production else RejectReason.BROKER_SERVER_MISMATCH)


async def test_right_before_each_exchange_order_a_ranking_follow_is_refused_on_a_production_login() -> None:
    """
    The broker asks what OrderExecution hands it right before it sends, as SinoPac's adapter does before each part. The
    settings on disk name the server the login is on, so the workflow alone refuses.
    """
    config = harness_config()
    users = FakeUserStore()
    users.add(ADMIN, None)

    async def sent(link: BrokerLink, workflow: Workflow) -> tuple[OrderStatus, str, int]:
        broker = RecordingExecutionProvider(link=link)
        switch = FakeOrderingSwitch(config.features, ShioajiServer.SIMULATION if link.simulation else ShioajiServer.PRODUCTION)
        execution = OrderExecution(
            broker, FakeTradingJournal(), users, switch, ADMIN.user_id, FakeMarketClock(NOW), config, SilentLogger()
        )
        order = await execution.execute(order_of(), run_stats(workflow))
        return order.status, (order.reason or "").split(":")[0], len(broker.placed)

    assert await sent(PRODUCTION, Workflow.RANKING_FOLLOW) == (OrderStatus.REJECTED, RejectReason.NOT_SIMULATION.name, 0)
    assert await sent(SIMULATION, Workflow.RANKING_FOLLOW) == (OrderStatus.FILLED, "", 1)
    assert await sent(PRODUCTION, Workflow.MANUAL_BUY) == (OrderStatus.FILLED, "", 1)
    assert await sent(MOCK, Workflow.RANKING_FOLLOW) == (OrderStatus.FILLED, "", 1)


def test_a_ranking_follow_may_order_on_sinopac_only_for_an_active_administrator_shown_ordering_on_an_up_simulation_login() -> None:
    rule = harness_config().follow_account_rule()
    sinopac = ExecutionProvider.SHIOAJI
    deactivated = replace(ADMIN, status=UserStatus.DEACTIVATED)

    def account(link: BrokerLink | None, user: User, ordering: SiteOrdering) -> tuple[tuple[ExecutionProvider, ...], Any]:
        links = {ExecutionProvider.MOCK: MOCK} | ({sinopac: link} if link is not None else {})
        chosen = rule.apply(replace(user, ranking_follow_broker=sinopac), links, ordering)
        return chosen.brokers, chosen.refusal

    mock_only = (ExecutionProvider.MOCK,)
    assert account(SIMULATION, ADMIN, SHOWN) == ((ExecutionProvider.MOCK, sinopac), None)
    assert account(None, ADMIN, SHOWN) == (mock_only, FollowAccountRefusal.BROKER_UNAVAILABLE)
    assert account(PRODUCTION, ADMIN, SHOWN) == (mock_only, FollowAccountRefusal.NOT_SIMULATION)
    assert account(SIMULATION, ADMIN, OFF) == (mock_only, FollowAccountRefusal.ORDERING_OFF)
    assert account(replace(SIMULATION, up=False), ADMIN, SHOWN) == (mock_only, FollowAccountRefusal.BROKER_UNAVAILABLE)
    assert account(replace(SIMULATION, simulation=False), ADMIN, SHOWN) == (mock_only, FollowAccountRefusal.NOT_SIMULATION)
    on_production = replace(SHOWN, server=ShioajiServer.PRODUCTION)
    assert account(SIMULATION, ADMIN, on_production) == (mock_only, FollowAccountRefusal.BROKER_UNAVAILABLE), (
        "a login off the server on disk"
    )
    for user, ordering in ((PLAIN, SHOWN), (PLAIN, EVERYONE), (deactivated, SHOWN)):
        for link in (SIMULATION, PRODUCTION, None):
            assert account(link, user, ordering)[1] == FollowAccountRefusal.ORDERING_OFF, "who may order comes first"


def test_on_a_real_broker_each_buy_is_sized_inside_the_order_limit_and_on_the_mock_account_at_its_equal_weight() -> None:
    config = harness_config()
    rule = config.ranking_follow_rule()
    stocks = {stock_id: Stock(stock_id=stock_id, realtime_bar=bar(NOW, price)) for stock_id, price in CLOSES.items()}
    ranked = [
        RankedStock(stock_id=stock_id, factors=[RankedFactor(value=1, rank=1), RankedFactor(value=1, rank=1)], score=2)
        for stock_id in ("2330", "2317")
    ]
    ranking = Ranking(
        formula=FORMULA, decided_on=date(2026, 10, 13), revenue_month=date(2026, 9, 1), universe=3, scored=3, stocks=ranked
    )
    account = Account(cash=1_000_000.0)

    def sized(broker: ExecutionProvider) -> dict[str, int]:
        return {buy.stock_id: buy.quantity for buy in rule.apply(ranking, account, stocks, NOW, broker) if not isinstance(buy, str)}

    limit = config.trading.max_order_value
    assert limit < 500_000
    assert sized(ExecutionProvider.MOCK) == {"2330": affordable(500_000, 100), "2317": affordable(500_000, 50)}
    assert sized(ExecutionProvider.SHIOAJI) == {"2330": affordable(limit, 100), "2317": affordable(limit, 50)}
    assert all(quantity * CLOSES[stock_id] <= limit for stock_id, quantity in sized(ExecutionProvider.SHIOAJI).items())


def test_on_sinopac_a_follows_buys_cost_no_more_than_the_cash_it_has_now_and_the_rest_wait_for_the_sales_to_settle() -> None:
    """SinoPac accepts a BUY on the cash it reports, which leaves a sale out until it settles; the mock account credits it at once."""
    config = harness_config()
    rule = config.ranking_follow_rule()
    stocks = {stock_id: Stock(stock_id=stock_id, realtime_bar=bar(NOW, price)) for stock_id, price in CLOSES.items()}
    ranked = [
        RankedStock(stock_id=stock_id, factors=[RankedFactor(value=1, rank=1), RankedFactor(value=1, rank=1)], score=2)
        for stock_id in ("2330", "2317")
    ]
    ranking = Ranking(
        formula=FORMULA, decided_on=date(2026, 10, 13), revenue_month=date(2026, 9, 1), universe=3, scored=3, stocks=ranked
    )
    left = next(stock_id for stock_id in CLOSES if stock_id not in ("2330", "2317"))
    cash = 150_000.0
    account = Account(cash=cash, positions=[Position(stock_id=left, quantity=10_000, average_cost=CLOSES[left])])
    cost_rule = rule.affordable_quantity_rule.cost_rule

    def decided(broker: ExecutionProvider) -> tuple[list[TradeSignal], list[str]]:
        answers = rule.apply(ranking, account, stocks, NOW, broker)
        return [answer for answer in answers if not isinstance(answer, str)], [answer for answer in answers if isinstance(answer, str)]

    def cost_of(buys: list[TradeSignal]) -> float:
        return sum(-cost_rule.apply(TradeAction.BUY, buy.stock_id, buy.price_at_signal, buy.quantity, now=NOW).net for buy in buys)

    on_mock, unfollowed_on_mock = decided(ExecutionProvider.MOCK)
    on_sinopac, waiting = decided(ExecutionProvider.SHIOAJI)
    buys_on_mock = [decision for decision in on_mock if decision.action == TradeAction.BUY]
    buys_on_sinopac = [decision for decision in on_sinopac if decision.action == TradeAction.BUY]

    assert [(sell.stock_id, sell.quantity) for sell in on_sinopac if sell.action == TradeAction.SELL] == [(left, 10_000)]
    assert [buy.stock_id for buy in buys_on_mock] == ["2330", "2317"] and not unfollowed_on_mock
    assert cost_of(buys_on_mock) > cash
    assert [(buy.stock_id, buy.quantity) for buy in buys_on_sinopac] == [("2330", affordable(config.trading.max_order_value, 100))]
    assert cost_of(buys_on_sinopac) <= cash
    assert len(waiting) == 1 and waiting[0].startswith("2317: a BUY of ") and "a sale's proceeds count once they settle" in waiting[0]
    assert [ExecutionProvider.MOCK.credits_sales_at_once, ExecutionProvider.SHIOAJI.credits_sales_at_once] == [True, False]


def test_on_sinopac_a_follow_between_a_sale_and_its_settlement_makes_no_buy_smaller_to_fit_the_cash_left() -> None:
    """The day after its sales the account's cash is what the first follow left; small BUYs now would end the decision short."""
    config = harness_config()
    rule = config.ranking_follow_rule()
    stocks = {stock_id: Stock(stock_id=stock_id, realtime_bar=bar(NOW, price)) for stock_id, price in CLOSES.items()}
    ranked = [
        RankedStock(stock_id=stock_id, factors=[RankedFactor(value=1, rank=1), RankedFactor(value=1, rank=1)], score=2)
        for stock_id in ("2330", "2317", "1101")
    ]
    ranking = Ranking(
        formula=FORMULA, decided_on=date(2026, 10, 13), revenue_month=date(2026, 9, 1), universe=3, scored=3, stocks=ranked
    )
    account = Account(cash=20_000.0, positions=[Position(stock_id="2330", quantity=1000, average_cost=100.0)])

    on_sinopac = rule.apply(ranking, account, stocks, NOW, ExecutionProvider.SHIOAJI)
    on_mock = rule.apply(ranking, account, stocks, NOW, ExecutionProvider.MOCK)

    assert [answer.split(":")[0] for answer in on_sinopac if isinstance(answer, str)] == ["2317", "1101"]
    assert not [answer for answer in on_sinopac if not isinstance(answer, str)]
    assert [(buy.stock_id, buy.quantity) for buy in on_mock if not isinstance(buy, str)] == [
        ("2317", affordable(10_000, 50)),
        ("1101", affordable(10_000, 30)),
    ]


def test_a_decision_is_finished_only_on_the_schedules_account_and_the_schedule_starts_once_a_day_on_any() -> None:
    sessions = weekdays(date(2026, 10, 1), date(2026, 10, 13))
    decided, now = date(2026, 10, 13), at(date(2026, 10, 15), 10)
    on_mock = follow(decided, at(date(2026, 10, 14), 9, 5), scheduled=True)
    on_sinopac = replace(on_mock, execution_provider=ExecutionProvider.SHIOAJI)

    def standing(broker: ExecutionProvider, *follows: Any) -> tuple[date | None, bool]:
        account = FollowAccount(broker=broker, brokers=tuple(ExecutionProvider), refusal=None, server=ShioajiServer.SIMULATION)
        schedule = RULE.apply(NINE_FIVE, sessions, follows, now, TradingPhase.CONTINUOUS, account)
        return schedule.pending, schedule.due

    assert standing(ExecutionProvider.SHIOAJI, on_mock) == (decided, True)
    assert standing(ExecutionProvider.MOCK, on_sinopac) == (decided, True)
    assert standing(ExecutionProvider.SHIOAJI, on_mock, on_sinopac) == (None, False)
    assert standing(ExecutionProvider.MOCK, on_mock, on_sinopac) == (None, False)
    refused = FollowAccount(broker=ExecutionProvider.SHIOAJI, brokers=(), refusal=FollowAccountRefusal.ORDERING_OFF, server=None)
    assert RULE.apply(NINE_FIVE, sessions, [on_mock], now, TradingPhase.CONTINUOUS, refused).due is False
    tried_today_on_mock = follow(decided, at(date(2026, 10, 15), 9, 5), scheduled=True, left=1)
    assert standing(ExecutionProvider.SHIOAJI, tried_today_on_mock) == (decided, False)
    assert standing(ExecutionProvider.SHIOAJI, replace(tried_today_on_mock, start_time=at(date(2026, 10, 14), 9, 5))) == (
        decided,
        True,
    )


# --------------------------------- Web API ------------------------------------ #


async def signed_in(client: httpx.AsyncClient, member: bool = False) -> None:
    name, password = (MEMBER.username, MEMBER_PASSWORD) if member else (ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)
    assert (await sign_in(client, name, password)).status_code == 200


def sent(broker: RecordingExecutionProvider) -> list[tuple[str, TradeAction, int]]:
    return [(order.stock_id, order.action, order.quantity) for order in broker.placed]


def on_production(harness: CliHarness) -> None:
    harness.real_broker.current_link = PRODUCTION


async def follow_on(client: httpx.AsyncClient, broker: str) -> httpx.Response:
    return await write(client, "PUT", "/v1/rankings/follow/account", {"broker": broker})


async def follow_ranking(client: httpx.AsyncClient, broker: str = "shioaji") -> httpx.Response:
    return await write(client, "POST", "/v1/rankings/follow", {"broker": broker})


async def account_of(client: httpx.AsyncClient) -> Any:
    return (await client.get("/v1/rankings/follow/schedule")).json()["account"]


async def on_sinopac(client: httpx.AsyncClient) -> None:
    assert (await follow_on(client, "shioaji")).status_code == 204


def saved_on_sinopac(harness: CliHarness, user: User) -> None:
    """A user saved as following on SinoPac, as one the site let choose it once is after they lost it."""
    harness.users.by_id[user.user_id] = replace(harness.users.by_id[user.user_id], ranking_follow_broker=ExecutionProvider.SHIOAJI)


async def test_a_follow_on_sinopac_brings_the_simulation_account_to_the_ranking_inside_the_buy_limit() -> None:
    harness = site(sinopac=True)
    harness.real_broker.positions = [(await harness.broker.get_account()).buy("1101", 1000, price=30.0, total_cost=30_000.0)]
    limit = harness.runtime.config.trading.max_order_value

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in(client)
        await on_sinopac(client)
        before = (await client.get("/v1/rankings/follow")).json()
        started = await follow_ranking(client)
        run = await ended(client, started.json()["run_id"])
        orders = (await client.get(f"/v1/runs/{started.json()['run_id']}/orders")).json()
        page = (await client.get("/v1/rankings/follow")).json()
        again = await follow_ranking(client)

    assert before["account"] == {"broker": "shioaji", "brokers": ["mock", "shioaji"], "refusal": None, "server": "simulation"}
    assert before["holdings"] == {"decided_on": "2026-10-13", "held": [], "lacking": ["2330", "2317"], "left": ["1101"]}
    assert (before["refusal"], before["performance"]) == (None, None)
    assert (started.status_code, run["state"], run["summary"]["execution_provider"]) == (202, "finished", "shioaji")
    assert sent(harness.real_broker) == [
        ("1101", TradeAction.SELL, 1000),
        ("2330", TradeAction.BUY, affordable(limit, 100)),
        ("2317", TradeAction.BUY, affordable(limit, 50)),
    ]
    assert [(order["stock_id"], order["status"]) for order in orders] == [("1101", "filled"), ("2330", "filled"), ("2317", "filled")]
    assert harness.broker.placed == [] and (await harness.broker.get_account()).positions == []
    assert [(row["run_id"], row["execution_provider"]) for row in page["follows"]] == [(started.json()["run_id"], "shioaji")]
    assert (page["holdings"]["held"], page["holdings"]["lacking"], page["holdings"]["left"]) == (["2330", "2317"], [], [])
    assert (page["refusal"], page["performance"]) == ("nothing_to_follow", None)
    assert (again.status_code, again.json()["code"]) == (409, "nothing_to_follow")
    assert [record.ranking_open for record in harness.journal.runs.values()] == [0]


async def test_the_ranking_block_on_sinopac_reads_its_positions_once_and_nothing_else_of_the_account() -> None:
    harness = site(sinopac=True)
    harness.real_broker.positions = [(await harness.broker.get_account()).buy("2330", 1000, price=100.0, total_cost=100_000.0)]

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in(client)
        await on_sinopac(client)
        page = (await client.get("/v1/rankings/follow")).json()

    assert harness.real_broker.requests == ["open_positions"]
    assert (page["holdings"]["held"], page["holdings"]["lacking"]) == (["2330"], ["2317"])
    assert harness.real_broker.placed == [] and harness.broker.placed == [] and harness.journal.runs == {}


async def test_on_a_production_login_a_follow_on_sinopac_is_refused_before_the_account_is_read_and_not_moved_to_the_mock_account() -> (
    None
):
    harness = site(sinopac=True)

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in(client)
        await on_sinopac(client)
        on_production(harness)
        refused = await follow_ranking(client)
        page = (await client.get("/v1/rankings/follow")).json()
        account = await account_of(client)
        timed = await write(client, "PUT", "/v1/rankings/follow/schedule", {"time": "09:05"})

    assert (refused.status_code, refused.json()["code"]) == (403, "not_simulation")
    assert (page["account"]["refusal"], page["refusal"]) == ("not_simulation", None)
    assert page["holdings"] == {"decided_on": "2026-10-13", "held": [], "lacking": [], "left": []}
    assert account == {"broker": "shioaji", "brokers": ["mock"], "refusal": "not_simulation", "server": "production"}
    assert (timed.status_code, timed.json()["code"]) == (403, "follow_broker_not_offered")
    assert harness.real_broker.requests == [], "SinoPac's account is not read"
    assert harness.real_broker.placed == [] and harness.broker.placed == [] and harness.journal.runs == {}


async def test_a_login_that_turns_out_to_be_production_during_a_run_gets_no_order_of_the_follow() -> None:
    harness = site(sinopac=True)
    user = replace(harness.administrator, ranking_follow_broker=ExecutionProvider.SHIOAJI)
    pipeline = harness.runtime.pipeline_for(user, ExecutionProvider.SHIOAJI)
    lookup = pipeline.stock_lookup.execute

    async def lookup_then_production(*arguments: Any) -> Any:
        on_production(harness)
        return await lookup(*arguments)

    pipeline.stock_lookup.execute = lookup_then_production  # type: ignore[method-assign]

    status = await pipeline.follow_ranking(user)

    assert [order.status.value for order in status.orders] == ["rejected", "rejected"]
    assert all(order.reason is not None and order.reason.startswith("NOT_SIMULATION") for order in status.orders)
    assert harness.real_broker.placed == [] and harness.broker.placed == [] and status.stats.ranking_open == 2


@pytest.mark.parametrize(
    ("member", "features"),
    [
        (True, {}),
        (True, {"sinopac_ordering": FeatureVisibility.EVERYONE, "sinopac_account": FeatureVisibility.EVERYONE}),
        (False, {"sinopac_ordering": FeatureVisibility.OFF}),
        (False, {"sinopac_account": FeatureVisibility.OFF}),
    ],
)
async def test_a_user_the_site_does_not_let_order_on_sinopac_is_refused_there_and_never_followed_on_the_mock_account(
    member: bool, features: dict[str, FeatureVisibility]
) -> None:
    harness = site(sinopac=True, features=features)
    saved_on_sinopac(harness, MEMBER if member else ADMINISTRATOR)

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in(client, member)
        refused = await follow_ranking(client)
        page = await client.get("/v1/rankings/follow")
        account = await account_of(client)
        timed = await write(client, "PUT", "/v1/rankings/follow/schedule", {"time": "09:05"})

    assert (refused.status_code, refused.json()["code"]) == (403, "ordering_off")
    assert page.status_code == 200, "a hidden account is the block's refusal, not a refused page"
    assert (page.json()["account"]["refusal"], page.json()["holdings"]["lacking"]) == ("ordering_off", [])
    assert (account["broker"], account["brokers"], account["refusal"]) == ("shioaji", ["mock"], "ordering_off")
    assert (timed.status_code, timed.json()["code"]) == (403, "follow_broker_not_offered")
    assert harness.real_broker.placed == [] and harness.broker.placed == [] and harness.journal.runs == {}


async def test_without_a_sinopac_login_the_site_offers_the_mock_account_alone_and_refuses_a_follow_saved_on_sinopac() -> None:
    harness = site()
    saved_on_sinopac(harness, ADMINISTRATOR)

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in(client)
        refused = await follow_ranking(client)
        page = (await client.get("/v1/rankings/follow")).json()
        back = await follow_on(client, "mock")
        on_mock = await follow_ranking(client, "mock")
        await ended(client, on_mock.json()["run_id"])

    assert (refused.status_code, refused.json()["code"]) == (403, "broker_unavailable")
    assert page["account"] == {"broker": "shioaji", "brokers": ["mock"], "refusal": "broker_unavailable", "server": None}
    assert back.status_code == 204
    assert (on_mock.status_code, len(harness.broker.placed)) == (202, 2), "the mock account follows once the user chose it"


# -------------------------------- The schedule -------------------------------- #


async def on_sinopac_from(client: httpx.AsyncClient, at_time: str = "09:05") -> None:
    await on_sinopac(client)
    assert (await write(client, "PUT", "/v1/rankings/follow/schedule", {"time": at_time})).status_code == 204


async def test_a_schedule_on_sinopac_follows_into_the_simulation_account_and_a_follow_of_the_mock_account_does_not_finish_it() -> None:
    harness = site(sinopac=True)

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in(client)
        by_hand = await follow_ranking(client, "mock")
        await ended(client, by_hand.json()["run_id"])
        await on_sinopac_from(client)
        settings = (await client.get("/v1/rankings/follow/schedule")).json()
        account, schedule = settings["account"], settings["schedule"]
        [run_id] = await look(app)
        run = await finished(harness, run_id)
        again = await look(app)
        after = (await client.get("/v1/rankings/follow")).json()

    assert (account["broker"], account["brokers"], schedule["pending"], schedule["due"]) == (
        "shioaji",
        ["mock", "shioaji"],
        "2026-10-13",
        True,
    )
    assert (run.workflow, run.execution_provider, run.scheduled, run.ranking_open) == (
        Workflow.RANKING_FOLLOW,
        ExecutionProvider.SHIOAJI,
        True,
        0,
    )
    assert [stock_id for stock_id, _, _ in sent(harness.real_broker)] == ["2330", "2317"]
    assert len(harness.broker.placed) == 2 and again == []
    assert [(row["execution_provider"], row["scheduled"]) for row in after["follows"]] == [("mock", False), ("shioaji", True)]
    assert (after["schedule"]["pending"], after["schedule"]["due"]) == (None, False)


async def test_a_schedule_on_the_mock_account_is_not_finished_by_a_follow_on_sinopac() -> None:
    harness = site(sinopac=True)

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in(client)
        await on_sinopac(client)
        by_hand = await follow_ranking(client)
        await ended(client, by_hand.json()["run_id"])
        assert (await follow_on(client, "mock")).status_code == 204
        assert (await write(client, "PUT", "/v1/rankings/follow/schedule", {"time": "09:05"})).status_code == 204
        [run_id] = await look(app)
        run = await finished(harness, run_id)

    assert (run.execution_provider, run.scheduled) == (ExecutionProvider.MOCK, True)
    assert len(harness.real_broker.placed) == 2 and len(harness.broker.placed) == 2


async def test_a_follow_on_sinopac_buys_with_the_cash_the_account_has_now_and_its_record_says_which_buy_waits() -> None:
    """SinoPac's cash leaves a sale out until it settles, so the BUY that only the sale would pay for is left to a later follow."""
    harness = site(sinopac=True)
    harness.real_broker.cash = 150_000.0
    harness.real_broker.positions = [(await harness.broker.get_account()).buy("1101", 10_000, price=30.0, total_cost=300_000.0)]
    limit = harness.runtime.config.trading.max_order_value

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in(client)
        await on_sinopac(client)
        started = await follow_ranking(client)
        run = await ended(client, started.json()["run_id"])
        again = await follow_ranking(client)
        second = await ended(client, again.json()["run_id"])

    waiting = [line for line in run["summary"]["execution_log"] if "Not followed now: 2317: a BUY of" in line]
    assert sent(harness.real_broker)[:2] == [("1101", TradeAction.SELL, 10_000), ("2330", TradeAction.BUY, affordable(limit, 100))]
    assert len(waiting) == 1 and "a sale's proceeds count once they settle" in waiting[0]
    assert [record.ranking_open for record in harness.journal.runs.values()] == [1, 0]
    assert sent(harness.real_broker)[2:] == [("2317", TradeAction.BUY, affordable(limit, 50))], "the fake credits the sale at once"
    assert second["summary"]["errors"] == [] and harness.broker.placed == []


async def test_the_follow_account_and_the_schedules_time_are_saved_apart() -> None:
    harness = site(sinopac=True)

    async def saved() -> tuple[time | None, ExecutionProvider]:
        user = harness.users.by_id[ADMINISTRATOR.user_id]
        return user.ranking_follow_time, user.ranking_follow_broker

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in(client)
        account_while_off = (await follow_on(client, "shioaji"), await saved())
        timed = (await write(client, "PUT", "/v1/rankings/follow/schedule", {"time": "10:00"}), await saved())
        moved = (await follow_on(client, "mock"), await saved())
        off = (await write(client, "PUT", "/v1/rankings/follow/schedule", {"time": None}), await saved())
        named = await write(client, "PUT", "/v1/rankings/follow/schedule", {"time": "09:05", "broker": "shioaji"})
        stale = await write(client, "POST", "/v1/rankings/follow", {"broker": "shioaji"})

    assert [(answer.status_code, kept) for answer, kept in (account_while_off, timed, moved, off)] == [
        (204, (None, ExecutionProvider.SHIOAJI)),
        (204, (time(10, 0), ExecutionProvider.SHIOAJI)),
        (204, (time(10, 0), ExecutionProvider.MOCK)),
        (204, (None, ExecutionProvider.MOCK)),
    ]
    assert (named.status_code, await saved()) == (422, (None, ExecutionProvider.MOCK)), (
        "an old page's schedule with an account saves nothing"
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "follow_account_changed"), (
        "the follow names the account the user confirmed"
    )
    assert harness.real_broker.placed == [] and harness.broker.placed == [] and harness.journal.runs == {}


def ordering_off(harness: CliHarness) -> None:
    features = harness.runtime.config.features.model_copy(update={"sinopac_ordering": FeatureVisibility.OFF})
    harness.dependencies.ordering_switch.features = features  # type: ignore[attr-defined]


def demoted(harness: CliHarness) -> None:
    harness.users.add(
        replace(MEMBER, user_id=UserId("u-other-admin"), username="other", email="other@example.com", role=Role.ADMINISTRATOR), None
    )
    harness.users.by_id[ADMINISTRATOR.user_id] = replace(harness.users.by_id[ADMINISTRATOR.user_id], role=Role.USER)


def login_down(harness: CliHarness) -> None:
    harness.real_broker.current_link = replace(SIMULATION, up=False)


@pytest.mark.parametrize(
    ("lose", "why"),
    [(ordering_off, "ordering_off"), (demoted, "ordering_off"), (login_down, "broker_unavailable"), (on_production, "not_simulation")],
)
async def test_a_user_who_lost_sinopac_is_followed_on_no_account_and_the_look_logs_why(lose: Any, why: str) -> None:
    harness = site(sinopac=True)

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in(client)
        await on_sinopac_from(client)
        lose(harness)
        started = [*await look(app), *await look(app)]
        settings = (await client.get("/v1/rankings/follow/schedule")).json()

    logged = [message for level, message in harness.logger.records if "does nothing now" in message]
    assert started == [] and harness.journal.runs == {}
    assert harness.real_broker.placed == [] and harness.broker.placed == []
    assert len(logged) == 1, "the timer looks every minute, and the reason is logged once a day"
    assert f"user {ADMINISTRATOR.user_id} on SinoPac" in logged[0] and why in logged[0]
    assert (settings["account"]["broker"], settings["account"]["brokers"]) == ("shioaji", ["mock"])
    assert settings["account"]["refusal"] == why and settings["schedule"]["due"] is False
    assert harness.users.by_id[ADMINISTRATOR.user_id].ranking_follow_broker == ExecutionProvider.SHIOAJI


async def test_a_user_who_changed_their_follow_account_during_the_look_is_not_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = site(sinopac=True)

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in(client)
        await on_sinopac_from(client)
        history = harness.dependencies.bar_matrix_provider.load_ranking_history

        async def history_then_moved() -> Any:
            loaded = await history()
            user = harness.users.by_id[ADMINISTRATOR.user_id]
            harness.users.by_id[ADMINISTRATOR.user_id] = replace(user, ranking_follow_broker=ExecutionProvider.MOCK)
            return loaded

        monkeypatch.setattr(harness.dependencies.bar_matrix_provider, "load_ranking_history", history_then_moved)
        started = await look(app)

    assert started == [] and harness.real_broker.placed == [] and harness.broker.placed == []


async def test_a_schedule_is_not_moved_to_an_account_that_cannot_follow_and_can_still_be_turned_off_and_never_moves_it() -> None:
    harness = site(sinopac=True)

    async with app_of(harness) as app, client_at(app) as client:
        await signed_in(client)
        await on_sinopac_from(client, "09:30")
        on_production(harness)
        later = await write(client, "PUT", "/v1/rankings/follow/schedule", {"time": "10:00"})
        kept = harness.users.by_id[ADMINISTRATOR.user_id]
        off = await write(client, "PUT", "/v1/rankings/follow/schedule", {"time": None})

    assert (later.status_code, later.json()["code"], off.status_code) == (403, "follow_broker_not_offered", 204)
    assert (kept.ranking_follow_time, kept.ranking_follow_broker) == (time(9, 30), ExecutionProvider.SHIOAJI)
    assert harness.users.by_id[ADMINISTRATOR.user_id].ranking_follow_time is None
    assert harness.users.by_id[ADMINISTRATOR.user_id].ranking_follow_broker == ExecutionProvider.SHIOAJI


async def test_a_run_that_started_on_another_account_than_the_follow_account_reads_and_sends_nothing() -> None:
    harness = site(sinopac=True)
    user = harness.administrator
    pipeline = harness.runtime.pipeline_for(user, ExecutionProvider.SHIOAJI)

    with pytest.raises(FollowAccountChanged):
        await pipeline.follow_ranking(user)

    [run] = harness.journal.runs.values()
    assert (run.execution_provider, run.failure is not None, run.ranking_open) == (ExecutionProvider.SHIOAJI, True, None)
    assert harness.real_broker.requests == [] and harness.real_broker.placed == [] and harness.broker.placed == []
