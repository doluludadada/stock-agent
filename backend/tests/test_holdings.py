"""
My holdings and the SinoPac account page over the Web API: the portfolio a mixed set of holdings makes, each holding
under its one source, who reads which source, the hand-entered holdings of each user, and that reading the SinoPac
account is separate from ordering on it: with features.sinopac_ordering off no order reaches SinoPac, at the routes and
at the send.
"""

import math
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from support.databases import open_database, raw_engine
from support.harness import (
    ADMINISTRATOR,
    ADMINISTRATOR_PASSWORD,
    MARKET_OPEN,
    MEMBER,
    MEMBER_PASSWORD,
    CliHarness,
    build_harness,
    rising_history,
    runtime_for,
)
from support.web import app_of, client_at, ended, serve, sign_in, write
from test_ranking import SESSIONS, bars, market, revenue
from test_web_api import FOLLOWED_RUN, SINOPAC_STARTS, reported_run

from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import BrokerFill, Position, Settlement
from a_domain.rules.trading.ranking import MonthlyRankingRule, Ranking
from a_domain.types.enums import ExecutionProvider, FeatureVisibility, OrderStatus, RejectReason, TradeAction
from a_domain.types.ids import UserId
from c_infrastructure.database.models.schema_version_dto import SCHEMA_VERSION
from c_infrastructure.database.repositories.holding_repository import HoldingRepository

pytestmark = pytest.mark.asyncio

OFF, ADMINISTRATORS, EVERYONE = FeatureVisibility.OFF, FeatureVisibility.ADMINISTRATORS, FeatureVisibility.EVERYONE
LAST_SESSION = SESSIONS[-1]
MANUAL = {"2330": (1000, 100.0), "1101": (37, 40.0), "0050": (100, 90.0), "2454": (200, 110.0)}
"""Entered by hand: a ranked stock, an odd lot of the lowest-ranked one, an ETF, and a stock with no revenue held."""


def showing(harness: CliHarness, **visibilities: FeatureVisibility) -> CliHarness:
    """
    The same site with these features' visibilities changed: a new runtime over the same ports, current as a settings
    save makes the one it opens.
    """
    config = harness.config.model_copy(update={"features": harness.config.features.model_copy(update=visibilities)})
    runtime = runtime_for(harness, config)
    runtime.become_current()
    return replace(harness, config=config, runtime=runtime)


def portfolio_site(**visibilities: FeatureVisibility) -> CliHarness:
    """
    The ranking tests' market (2330 scores 100, 2317 50, 1101 0; the ranking holds two) with an ETF and a stock without
    revenue listed, SinoPac offered, a member beside the administrator, and the administrator holding 2317 on the mock
    account and 2330 at SinoPac.
    """
    base = market()
    config = base.config.model_copy(update={"features": base.config.features.model_copy(update=visibilities)})
    harness = build_harness(config=config, sinopac=True)

    for stock_id, history in base.prices.history.items():
        harness.list_stock(stock_id, history)

    harness.archive.monthly_revenues.update(base.archive.monthly_revenues)

    for (stock_id, _, _), month in sorted(base.archive.monthly_revenues.items()):
        harness.archive.held_financials.setdefault(stock_id, ([], []))[1].append(month)

    harness.list_stock("0050", bars([100, 101, 102, 103, 104]))
    harness.list_stock("2454", bars([100, 101, 102, 103, 104]))
    harness.users.add(MEMBER, MEMBER_PASSWORD)
    harness.hold("2317", quantity=1000, average_cost=60.0)
    harness.real_broker.positions = [Position(stock_id="2330", quantity=500, average_cost=95.0)]
    return harness


async def enter(client: Any, stock_id: str, quantity: int, average_cost: float, **more: Any) -> Any:
    return await write(
        client, "POST", "/v1/holdings/manual", {"stock_id": stock_id, "quantity": quantity, "average_cost": average_cost, **more}
    )


async def enter_all(client: Any) -> None:
    for stock_id, (quantity, average_cost) in MANUAL.items():
        assert (await enter(client, stock_id, quantity, average_cost)).status_code == 200


def rows(body: dict[str, Any]) -> list[tuple[str, str]]:
    return [(holding["source"], holding["position"]["stock_id"]) for holding in body["holdings"]]


# ------------------------------------------------------ the portfolio ------------------------------------------------------ #


async def test_a_mixed_portfolio_keeps_each_holding_under_its_source_and_reads_them_as_one() -> None:
    harness = portfolio_site()

    async with serve(harness) as client:
        await enter_all(client)
        body = (await client.get("/v1/holdings")).json()

    total = 104_000 + 54_000 + 52_000 + 20_800 + 10_400 + 1_258
    scored = 104_000 + 54_000 + 52_000 + 1_258
    assert (body["asked"], body["sources"]) == (["brokerage", "manual", "mock"], ["brokerage", "manual", "mock"])
    assert rows(body) == [
        ("manual", "2330"),
        ("mock", "2317"),
        ("brokerage", "2330"),
        ("manual", "2454"),
        ("manual", "0050"),
        ("manual", "1101"),
    ]
    assert (body["market_value"], body["cost"]) == (total, 100_000 + 60_000 + 47_500 + 22_000 + 9_000 + 1_480)
    assert [holding["weight"] for holding in body["holdings"]] == pytest.approx(
        [104_000 / total, 54_000 / total, 52_000 / total, 20_800 / total, 10_400 / total, 1_258 / total]
    )
    assert (body["concentration_positions"], body["concentration"]) == (3, pytest.approx((156_000 + 54_000 + 20_800) / total))
    assert body["top_share"] == pytest.approx((156_000 + 54_000) / total)
    assert body["scored_share"] == pytest.approx(scored / total)
    assert body["weighted_score"] == pytest.approx((156_000 * 100 + 54_000 * 50) / scored)
    assert (body["lowest"]["position"]["stock_id"], body["lowest"]["standing"]["score"]) == ("1101", 0.0)
    assert (body["highest"]["source"], body["highest"]["position"]["stock_id"], body["highest"]["standing"]["score"]) == (
        "manual",
        "2330",
        100.0,
    )


async def test_a_holding_is_valued_at_the_last_close_held_net_of_the_costs_of_selling_it() -> None:
    harness = portfolio_site()

    async with serve(harness) as client:
        await enter_all(client)
        body = (await client.get("/v1/holdings", params={"sources": ["manual"]})).json()

    held = {holding["position"]["stock_id"]: holding for holding in body["holdings"]}
    valued = harness.config.market.position_value_rule().apply(
        Position(stock_id="2330", quantity=1000, average_cost=100.0), 104.0, harness.clock.session_close(LAST_SESSION)
    )
    best, odd_lot = held["2330"], held["1101"]

    assert (best["stock_name"], best["position"]["mark_price"], best["position"]["marked_at"][:10]) == (
        "Stock 2330",
        104.0,
        LAST_SESSION.isoformat(),
    )
    assert (best["position"]["market_value"], best["position"]["cost_basis"]) == (104_000, 100_000)
    assert best["position"]["unrealized_pnl"] == pytest.approx(valued.unrealized_pnl)
    assert 3_000 < best["position"]["unrealized_pnl"] < 4_000
    assert best["position"]["unrealized_return"] == pytest.approx(valued.unrealized_pnl / 100_000)
    assert (odd_lot["position"]["quantity"], odd_lot["position"]["market_value"]) == (37, 37 * 34)
    assert body["unrealized_pnl"] == pytest.approx(math.fsum(holding["position"]["unrealized_pnl"] for holding in body["holdings"]))
    assert body["unrealized_return"] == pytest.approx(body["unrealized_pnl"] / body["cost"])


async def test_each_holding_carries_the_stock_pages_own_standing_or_why_it_has_no_score() -> None:
    harness = portfolio_site()

    async with serve(harness) as client:
        await enter_all(client)
        body = (await client.get("/v1/holdings", params={"sources": ["manual"]})).json()
        pages = {stock_id: (await client.get(f"/v1/market/stocks/{stock_id}/ranking")).json() for stock_id in MANUAL}

    held = {holding["position"]["stock_id"]: holding for holding in body["holdings"]}

    assert {stock_id: holding["standing"] for stock_id, holding in held.items()} == pages
    assert {stock_id: (holding["standing"]["score"], holding["standing"]["exclusion"]) for stock_id, holding in held.items()} == {
        "2330": (100.0, None),
        "1101": (0.0, None),
        "0050": (None, "not_a_stock"),
        "2454": (None, "no_revenue_history"),
    }
    assert (held["2330"]["revenue"]["acceleration"], held["2330"]["accelerating_months"]) == (pytest.approx(4 / 3), 1)
    assert (held["1101"]["revenue"]["acceleration"], held["1101"]["accelerating_months"]) == (pytest.approx(2 / 3), -1)
    assert (held["0050"]["revenue"], held["0050"]["accelerating_months"]) == (None, None)
    assert (held["2454"]["revenue"], held["2454"]["accelerating_months"]) == (None, None)


async def test_the_holdings_rank_the_market_three_times_however_many_stocks_are_held(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = portfolio_site()
    harness.stocks.stocks["6789"] = Stock(stock_id="6789", name="Unpriced")
    harness.list_stock("3008", bars([5, 5, 5, 5, 5]))
    harness.list_stock("6547", [replace(bar, volume=1) for bar in bars([100, 101, 102, 103, 104])])
    harness.list_stock("6898", bars([100, 101, 102, 103, 104])[3:])

    for stock_id in ("0050", "3008", "6547", "6898"):
        for month in (1, 2):
            harness.archive.monthly_revenues[(stock_id, 2026, month)] = revenue(stock_id, 2026, month, 100.0)

    held = (*MANUAL, "2317", "6789", "3008", "6547", "6898")
    rank = MonthlyRankingRule.apply
    ranked: list[MonthlyRankingRule] = []

    def counted(rule: MonthlyRankingRule, *arguments: Any) -> Ranking:
        ranked.append(rule)
        return rank(rule, *arguments)

    async with serve(harness) as client:
        for stock_id in held:
            assert (await enter(client, stock_id, 100, 50.0)).status_code == 200

        pages = {stock_id: (await client.get(f"/v1/market/stocks/{stock_id}/ranking")).json() for stock_id in held}
        monkeypatch.setattr(MonthlyRankingRule, "apply", counted)
        body = (await client.get("/v1/holdings", params={"sources": ["manual"]})).json()

    standings = {holding["position"]["stock_id"]: holding["standing"] for holding in body["holdings"]}

    assert standings == pages
    assert {stock_id: standing["exclusion"] or standing["place"] for stock_id, standing in standings.items()} == {
        "2330": 1,
        "2317": 2,
        "1101": 3,
        "6789": "no_history",
        "0050": "not_a_stock",
        "6898": "not_traded",
        "6547": "illiquid",
        "3008": "price_under_floor",
        "2454": "no_revenue_history",
    }
    assert [(rule.min_traded_value > 0, rule.min_close > 0) for rule in ranked] == [(True, True), (False, True), (False, False)]


async def test_a_stock_the_site_holds_no_close_of_counts_at_its_cost_and_says_it_has_no_price() -> None:
    harness = portfolio_site()
    harness.stocks.stocks["6789"] = Stock(stock_id="6789", name="Unpriced")

    async with serve(harness) as client:
        await enter(client, "6789", 10, 50.0)
        [holding] = (await client.get("/v1/holdings", params={"sources": ["manual"]})).json()["holdings"]

    assert (holding["position"]["marked_at"], holding["position"]["market_value"], holding["position"]["unrealized_return"]) == (
        None,
        500,
        None,
    )
    assert holding["standing"]["exclusion"] == "no_history"


async def test_the_portfolios_return_is_over_the_cost_of_the_holdings_that_have_a_price_alone() -> None:
    harness = portfolio_site()
    harness.stocks.stocks["6789"] = Stock(stock_id="6789", name="Unpriced")

    async with serve(harness) as client:
        await enter(client, "6789", 4000, 50.0)
        unpriced = (await client.get("/v1/holdings", params={"sources": ["manual"]})).json()
        await enter(client, "2330", 1000, 100.0)
        body = (await client.get("/v1/holdings", params={"sources": ["manual"]})).json()

    priced = next(holding["position"] for holding in body["holdings"] if holding["position"]["stock_id"] == "2330")

    assert (body["cost"], body["unrealized_pnl"]) == (300_000, priced["unrealized_pnl"])
    assert body["unrealized_return"] == pytest.approx(priced["unrealized_pnl"] / 100_000)
    assert (unpriced["cost"], unpriced["unrealized_pnl"], unpriced["unrealized_return"]) == (200_000, 0, None)


async def test_the_sources_asked_for_narrow_the_portfolio_and_an_empty_one_is_all_zero() -> None:
    harness = portfolio_site()

    async with serve(harness) as client:
        empty = (await client.get("/v1/holdings", params={"sources": ["manual"]})).json()
        await enter_all(client)
        mock = (await client.get("/v1/holdings", params={"sources": ["mock"]})).json()
        both = (await client.get("/v1/holdings", params={"sources": ["mock", "brokerage"]})).json()
        unknown = await client.get("/v1/holdings", params={"sources": ["bank"]})

    assert (empty["holdings"], empty["market_value"], empty["weighted_score"], empty["unrealized_return"]) == ([], 0, None, None)
    assert (mock["asked"], rows(mock), mock["concentration"]) == (["mock"], [("mock", "2317")], 1.0)
    assert rows(both) == [("mock", "2317"), ("brokerage", "2330")]
    assert unknown.status_code == 422


async def test_the_score_figures_are_withheld_from_a_viewer_the_site_does_not_show_the_ranking() -> None:
    harness = portfolio_site(ranking=OFF)

    async with serve(harness) as client:
        await enter_all(client)
        body = (await client.get("/v1/holdings")).json()

    assert {holding["standing"] for holding in body["holdings"]} == {None}
    assert [body[name] for name in ("top_share", "scored_share", "weighted_score", "lowest", "highest")] == [None] * 5
    assert body["market_value"] == 242_458


async def test_the_holdings_answer_ranking_unavailable_while_the_history_holds_no_decision_session() -> None:
    async with serve(build_harness()) as client:
        answer = await client.get("/v1/holdings")

    assert (answer.status_code, answer.json()["code"]) == (422, "ranking_unavailable")


# ------------------------------------------------ who reads which source ------------------------------------------------ #


async def test_a_user_reads_only_the_sources_the_site_shows_them_and_never_the_sites_sinopac_account() -> None:
    harness = portfolio_site(mock_account=ADMINISTRATORS)

    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as client:
        await enter(client, "2317", 10, 50.0)
        member = (await client.get("/v1/holdings", params={"sources": ["brokerage", "mock", "manual"]})).json()

    async with serve(harness) as client:
        administrator = (await client.get("/v1/holdings")).json()

    assert (member["asked"], member["sources"], rows(member)) == (["manual"], ["manual"], [("manual", "2317")])
    assert (administrator["asked"], rows(administrator)) == (
        ["brokerage", "manual", "mock"],
        [("mock", "2317"), ("brokerage", "2330")],
    )


async def test_hiding_the_sinopac_account_leaves_its_holdings_out_even_for_an_administrator() -> None:
    async with serve(portfolio_site(sinopac_account=OFF)) as client:
        body = (await client.get("/v1/holdings")).json()

    assert (body["asked"], rows(body)) == (["manual", "mock"], [("mock", "2317")])


async def test_a_sinopac_login_that_is_down_is_asked_for_and_not_read() -> None:
    harness = portfolio_site()
    harness.real_broker.current_link = replace(harness.real_broker.current_link, up=False)

    async with serve(harness) as client:
        body = (await client.get("/v1/holdings")).json()

    assert (body["asked"], body["sources"], rows(body)) == (["brokerage", "manual", "mock"], ["manual", "mock"], [("mock", "2317")])


async def test_the_holdings_page_is_refused_where_the_site_hides_it_and_to_a_visitor() -> None:
    harness = portfolio_site(holdings=OFF)

    async with serve(harness) as client:
        read = await client.get("/v1/holdings")
        entered = await enter(client, "2330", 1, 1.0)
        removed = await write(client, "POST", "/v1/holdings/manual/remove", {"stock_id": "2330"})

    async with serve(portfolio_site(), authorized=False) as visitor:
        signed_out = await visitor.get("/v1/holdings")

    assert [(answer.status_code, answer.json()["code"]) for answer in (read, entered, removed)] == [(403, "feature_hidden")] * 3
    assert (signed_out.status_code, harness.holdings.holdings) == (401, {})


# ------------------------------------------------ the hand-entered holdings ------------------------------------------------ #


async def test_each_user_enters_reads_and_removes_only_their_own_holdings() -> None:
    harness = portfolio_site(mock_account=OFF, sinopac_account=OFF)

    async with app_of(harness) as app, client_at(app) as alice, client_at(app) as bob:
        await sign_in(alice, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)
        await sign_in(bob, MEMBER.username, MEMBER_PASSWORD)
        await enter(alice, "2330", 1000, 100.0)
        await enter(bob, "2330", 5, 90.0)
        await enter(bob, "2317", 7, 50.0)
        bob_removes = await write(bob, "POST", "/v1/holdings/manual/remove", {"stock_id": "2317"})
        bob_removes_again = await write(bob, "POST", "/v1/holdings/manual/remove", {"stock_id": "2317"})
        alices, bobs = (await alice.get("/v1/holdings")).json(), (await bob.get("/v1/holdings")).json()

    assert [(holding["position"]["stock_id"], holding["position"]["quantity"]) for holding in alices["holdings"]] == [("2330", 1000)]
    assert [(holding["position"]["stock_id"], holding["position"]["quantity"]) for holding in bobs["holdings"]] == [("2330", 5)]
    assert (bob_removes.status_code, bob_removes_again.status_code, bob_removes_again.json()["code"]) == (204, 404, "not_found")
    assert set(harness.holdings.holdings) == {"2330"} and set(harness.owners[MEMBER.user_id].holding_repository.holdings) == {"2330"}


async def test_an_entry_replaces_the_stocks_earlier_one_and_keeps_the_day_it_was_bought() -> None:
    harness = portfolio_site(mock_account=OFF, sinopac_account=OFF)

    async with serve(harness) as client:
        first = await enter(client, "2330", 1000, 100.0)
        second = await enter(client, "2330", 1500, 98.5, opened_on="2026-03-12")
        body = (await client.get("/v1/holdings")).json()

    [holding] = body["holdings"]
    assert (first.json()["opened_at"], second.json()["quantity"]) == (None, 1500)
    assert (holding["position"]["quantity"], holding["position"]["average_cost"]) == (1500, 98.5)
    assert harness.clock.to_trading_date(harness.holdings.holdings["2330"].opened_at).isoformat() == "2026-03-12"


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ({"stock_id": "9999", "quantity": 1, "average_cost": 10}, "unlisted_stock"),
        ({"stock_id": "2330", "quantity": 0, "average_cost": 10}, "greater_than"),
        ({"stock_id": "2330", "quantity": 1.5, "average_cost": 10}, "int_from_float"),
        ({"stock_id": "2330", "quantity": 1, "average_cost": 0}, "greater_than"),
        ({"stock_id": "2330", "quantity": 1, "average_cost": "inf"}, "finite_number"),
        ({"stock_id": "23 30", "quantity": 1, "average_cost": 10}, "string_pattern_mismatch"),
        ({"stock_id": "2330", "quantity": 1, "average_cost": 10, "opened_on": "yesterday"}, "date_from_datetime_parsing"),
    ],
    ids=["unlisted", "no-shares", "half-a-share", "free", "infinite-cost", "not-an-id", "not-a-date"],
)
async def test_an_entry_the_boundary_refuses_keeps_nothing(body: dict[str, Any], problem: str) -> None:
    harness = portfolio_site()

    async with serve(harness) as client:
        refused = await write(client, "POST", "/v1/holdings/manual", body)
        unconfirmed = await client.post("/v1/holdings/manual", json={"stock_id": "2330", "quantity": 1, "average_cost": 10})

    assert (refused.status_code, refused.json()["detail"][0]["type"], unconfirmed.status_code) == (422, problem, 422)
    assert harness.holdings.holdings == {}


async def test_entering_and_removing_a_holding_orders_nothing_and_touches_no_account() -> None:
    harness = portfolio_site()

    async with serve(harness) as client:
        await enter_all(client)
        await write(client, "POST", "/v1/holdings/manual/remove", {"stock_id": "2330"})
        await client.get("/v1/holdings")
        watchlist = (await client.get("/v1/watchlist")).json()

    assert (harness.broker.placed, harness.real_broker.placed, harness.journal.runs, watchlist) == ([], [], {}, [])
    assert [position.stock_id for position in harness.broker.positions] == ["2317"]


# --------------------------------------------- the manual holdings table --------------------------------------------- #


async def test_a_database_made_before_the_holdings_gains_their_table_at_the_next_start_and_keeps_its_rows(tmp_path: Path) -> None:
    before = open_database(tmp_path)
    await before.init_db()
    await before.close()
    engine = raw_engine()

    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE manual_holdings"))
        await connection.execute(
            text(
                "INSERT INTO watchlists (owner_id, stock_id, type, created_at) VALUES ('alice', '2330', 'manual', '2026-10-19 02:00')"
            )
        )

    database = open_database(tmp_path)
    await database.init_db()
    alice, bob = (HoldingRepository(database.for_owner(UserId(owner))) for owner in ("alice", "bob"))
    await alice.save(Position(stock_id="2330", quantity=37, average_cost=612.5, opened_at=MARKET_OPEN))
    await alice.save(Position(stock_id="2330", quantity=38, average_cost=610.0))
    await bob.save(Position(stock_id="0050", quantity=1000, average_cost=180.0, opened_at=MARKET_OPEN - timedelta(days=30)))

    async with engine.connect() as connection:
        stamps = list((await connection.execute(text("SELECT version FROM schema_version"))).scalars())
        watched = list((await connection.execute(text("SELECT owner_id, stock_id FROM watchlists"))).all())
        stored = list(
            (await connection.execute(text("SELECT owner_id, stock_id, quantity FROM manual_holdings ORDER BY owner_id"))).all()
        )

    assert (stamps, watched, stored) == ([SCHEMA_VERSION], [("alice", "2330")], [("alice", "2330", 38), ("bob", "0050", 1000)])
    assert [(held.quantity, held.average_cost, held.opened_at) for held in await alice.get_all()] == [(38, 610.0, None)]
    assert [held.opened_at for held in await bob.get_all()] == [MARKET_OPEN - timedelta(days=30)]
    await engine.dispose()
    await database.close()


# ------------------------------------------------- the SinoPac account ------------------------------------------------- #


def with_statement(harness: CliHarness) -> CliHarness:
    """SinoPac reporting a settlement due, a deal of today and two sales, one older than the page reads."""
    today = harness.clock.today()
    broker = harness.real_broker
    broker.cash = 42_000.0
    broker.settlements = [Settlement(settles_on=today + timedelta(days=2), amount=-47_500.0)]
    broker.fills = [BrokerFill(stock_id="2330", action=TradeAction.BUY, quantity=500, price=95.0, filled_on=today)]
    broker.sales = [
        BrokerFill(
            stock_id="2317",
            action=TradeAction.SELL,
            quantity=1000,
            price=58.0,
            filled_on=today - timedelta(days=10),
            realized_pnl=-2_300.0,
        ),
        BrokerFill(
            stock_id="1101", action=TradeAction.SELL, quantity=37, price=35.0, filled_on=today - timedelta(days=400), realized_pnl=10.0
        ),
    ]
    return harness


async def test_an_administrator_reads_the_sinopac_account_as_the_broker_reports_it_while_the_site_cannot_order_on_it() -> None:
    harness = with_statement(portfolio_site(sinopac_ordering=OFF))

    async with serve(harness) as client:
        answer = await client.get("/v1/account/brokerage")
        brokers = [broker["broker"] for broker in (await client.get("/v1/account/brokers")).json()]
        history = await client.get("/v1/account/history", params={"broker": "shioaji"})

    body = answer.json()
    statement = body["statement"]
    assert (answer.status_code, body["simulation"], body["login_up"], body["ordering"]) == (200, True, True, False)
    assert (statement["balance"], statement["settlements"]) == (42_000, [{"settles_on": "2026-10-21", "amount": -47_500}])
    assert [(held["stock_id"], held["quantity"], held["average_cost"]) for held in statement["positions"]] == [("2330", 500, 95)]
    assert [(fill["stock_id"], fill["action"], fill["quantity"], fill["price"]) for fill in statement["fills"]] == [
        ("2330", "buy", 500, 95)
    ]
    assert [(sale["stock_id"], sale["realized_pnl"]) for sale in statement["sales"]] == [("2317", -2_300)]
    assert (statement["sales_from"], statement["realized_pnl"]) == ("2026-07-21", -2_300)
    assert (brokers, history.status_code) == (["mock"], 200)
    assert "account_id" not in answer.text and "person" not in answer.text
    assert harness.real_broker.placed == []


async def test_the_sinopac_account_says_which_server_it_is_and_when_its_login_is_down() -> None:
    down = portfolio_site()
    down.real_broker.current_link = replace(down.real_broker.current_link, up=False)

    async with serve(down) as client:
        login_down = (await client.get("/v1/account/brokerage")).json()

    async with serve(build_harness()) as client:
        no_login = (await client.get("/v1/account/brokerage")).json()

    async with serve(portfolio_site()) as client:
        ordering_on = (await client.get("/v1/account/brokerage")).json()

    assert login_down == {"simulation": True, "login_up": False, "ordering": True, "statement": None}
    assert no_login == {"simulation": True, "login_up": False, "ordering": True, "statement": None}
    assert (ordering_on["login_up"], ordering_on["ordering"], ordering_on["statement"]["positions"][0]["stock_id"]) == (
        True,
        True,
        "2330",
    )


@pytest.mark.parametrize(
    ("visibility", "administrator", "member"),
    [(OFF, "feature_hidden", "feature_hidden"), (ADMINISTRATORS, None, "feature_hidden"), (EVERYONE, None, "administrators_only")],
)
async def test_the_sinopac_account_is_read_by_visibility_and_never_by_a_user_who_may_not_hold_the_broker(
    visibility: FeatureVisibility, administrator: str | None, member: str
) -> None:
    harness = portfolio_site(sinopac_account=visibility)

    async with app_of(harness) as app, client_at(app) as visitor, client_at(app) as as_member, client_at(app) as as_administrator:
        await sign_in(as_member, MEMBER.username, MEMBER_PASSWORD)
        await sign_in(as_administrator, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)
        signed_out = await visitor.get("/v1/account/brokerage")
        refused = await as_member.get("/v1/account/brokerage")
        answered = await as_administrator.get("/v1/account/brokerage")
        history = await as_administrator.get("/v1/account/history", params={"broker": "shioaji"})

    assert (signed_out.status_code, refused.status_code, refused.json()["code"]) == (401, 403, member)
    assert answered.json().get("code") == administrator and history.json().get("code") == administrator


# --------------------------------------- no order reaches SinoPac while ordering is off --------------------------------------- #


@pytest.mark.parametrize(("path", "body"), SINOPAC_STARTS)
async def test_with_ordering_off_every_order_route_refuses_sinopac_to_an_administrator_on_an_up_login(
    path: str, body: dict[str, Any]
) -> None:
    harness = build_harness(sinopac=True)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    off = showing(harness, sinopac_ordering=OFF)

    async with serve(harness) as client:
        run_id = await reported_run(client)

    runs_before = set(harness.journal.runs)

    async with serve(off) as client:
        route = path.replace(FOLLOWED_RUN, run_id)
        refused = await client.post(route, params={"broker": "shioaji"}, json={"confirm": True, **body})
        on_mock = await client.post(route, json={"confirm": True, **body})
        await ended(client, on_mock.json()["run_id"])

    assert (refused.status_code, refused.json()["code"], on_mock.status_code) == (403, "feature_hidden", 202)
    assert harness.real_broker.placed == []
    assert all(
        run.execution_provider == ExecutionProvider.MOCK for run_id, run in harness.journal.runs.items() if run_id not in runs_before
    )


@pytest.mark.parametrize("environment_is_up", [True, False], ids=["login-up", "login-down"])
async def test_with_ordering_off_a_run_that_holds_sinopac_has_every_order_refused_at_the_send(environment_is_up: bool) -> None:
    harness = build_harness(sinopac=True)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.list_stock("2317", rising_history(100.0), realtime_price=80.0)
    harness.real_broker.positions = [Position(stock_id="2317", quantity=1000, average_cost=100.0)]
    off = showing(harness, sinopac_ordering=OFF)
    pipeline = off.runtime.pipeline_for(off.administrator, ExecutionProvider.SHIOAJI)
    harness.real_broker.current_link = replace(harness.real_broker.current_link, up=environment_is_up)

    status = await pipeline.run_intraday()

    assert status.orders and {order.status for order in status.orders} == {OrderStatus.REJECTED}
    assert {order.reason for order in status.orders} == {
        f"{RejectReason.ORDERING_OFF.name}: this site has ordering on shioaji off: features.sinopac_ordering"
    }
    assert harness.real_broker.placed == [] and harness.broker.placed == []


async def test_the_cli_offers_sinopac_for_a_run_only_while_the_site_lets_the_user_order_on_it() -> None:
    harness = build_harness(sinopac=True)

    assert harness.runtime.brokers_for(harness.administrator) == [ExecutionProvider.MOCK, ExecutionProvider.SHIOAJI]
    assert showing(harness, sinopac_ordering=OFF).runtime.brokers_for(harness.administrator) == [ExecutionProvider.MOCK]
    assert showing(harness, sinopac_ordering=ADMINISTRATORS).runtime.brokers_for(harness.administrator) == [
        ExecutionProvider.MOCK,
        ExecutionProvider.SHIOAJI,
    ]
