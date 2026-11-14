"""
Whom the site shows each feature to (features.* in appsetting.yaml): the Web API refuses a hidden feature's routes, tells
the web app each feature's visibility, and never lets a visibility stand in for a broker's own gates.
"""

import pytest
from support.harness import MEMBER, MEMBER_PASSWORD, CliHarness, build_harness, harness_config
from support.settings import shipped_config
from support.web import app_of, client_at, serve, sign_in

from a_domain.types.enums import Feature, FeatureVisibility, Role
from b_application.config.api_config import FeaturesConfig

pytestmark = pytest.mark.asyncio

OFF, ADMINISTRATORS, EVERYONE = FeatureVisibility.OFF, FeatureVisibility.ADMINISTRATORS, FeatureVisibility.EVERYONE


def harness_showing(sinopac: bool = False, **visibilities: FeatureVisibility) -> CliHarness:
    """A site with a member beside the administrator, every feature shown to everyone but the ones named."""
    config = harness_config()
    harness = build_harness(
        config=config.model_copy(update={"features": config.features.model_copy(update=visibilities)}), sinopac=sinopac
    )
    harness.users.add(MEMBER, MEMBER_PASSWORD)
    return harness


def test_the_features_settings_are_the_feature_registry_and_the_shipped_file_sets_their_defaults() -> None:
    assert list(FeaturesConfig.model_fields) == [feature.value for feature in Feature]
    assert shipped_config().features == FeaturesConfig()


def test_the_shipped_site_shows_a_user_the_research_pages_and_an_administrator_everything() -> None:
    features = shipped_config().features
    research = {Feature.MARKET_OVERVIEW, Feature.RANKING, Feature.STOCK_PAGES, Feature.WATCHLIST, Feature.HOLDINGS}

    assert features.shown(Role.USER.permissions) == research
    assert features.shown(frozenset()) == research
    assert features.shown(Role.ADMINISTRATOR.permissions) == set(Feature) - {Feature.SINOPAC_ORDERING}
    assert features.sinopac_ordering == OFF


@pytest.mark.parametrize(
    ("visibility", "administrator", "member"), [(OFF, 403, 403), (ADMINISTRATORS, 200, 403), (EVERYONE, 200, 200)]
)
async def test_a_private_route_answers_each_role_by_its_features_visibility(
    visibility: FeatureVisibility, administrator: int, member: int
) -> None:
    harness = harness_showing(watchlist=visibility)

    async with app_of(harness) as app, client_at(app) as visitor, client_at(app) as as_member:
        await sign_in(as_member, MEMBER.username, MEMBER_PASSWORD)
        signed_out = await visitor.get("/v1/watchlist")
        refused = await as_member.get("/v1/watchlist")

    async with serve(harness) as as_administrator:
        answered = await as_administrator.get("/v1/watchlist")

    assert (signed_out.status_code, answered.status_code, refused.status_code) == (401, administrator, member)

    if member == 403:
        assert refused.json() == {"detail": "This site does not show this feature to you.", "code": "feature_hidden"}


@pytest.mark.parametrize(
    ("visibility", "visitor", "administrator"), [(OFF, True, True), (ADMINISTRATORS, True, False), (EVERYONE, False, False)]
)
async def test_a_route_that_needs_no_sign_in_hides_from_a_visitor_unless_everyone_sees_its_feature(
    visibility: FeatureVisibility, visitor: bool, administrator: bool
) -> None:
    harness = harness_showing(market_overview=visibility)

    async with serve(harness, authorized=False) as signed_out:
        seen_by_visitor = await signed_out.get("/v1/market/most-traded")

    async with serve(harness) as as_administrator:
        seen_by_administrator = await as_administrator.get("/v1/market/most-traded")

    assert ["feature_hidden" in answer.text for answer in (seen_by_visitor, seen_by_administrator)] == [visitor, administrator]


async def test_the_first_question_answers_every_features_visibility_to_a_visitor() -> None:
    async with serve(harness_showing(ranking=OFF, buzz=ADMINISTRATORS), authorized=False) as client:
        features = (await client.get("/v1/auth/status")).json()["features"]

    assert set(features) == {feature.value for feature in Feature}
    assert (features["ranking"], features["buzz"], features["watchlist"]) == ("off", "administrators", "everyone")


async def test_a_user_who_may_start_no_run_has_no_runs_and_one_kind_shown_opens_them() -> None:
    kinds = {"full_cycle": ADMINISTRATORS, "specific_stock": ADMINISTRATORS, "buzz": ADMINISTRATORS, "intraday": ADMINISTRATORS}
    member = (MEMBER.username, MEMBER_PASSWORD)

    async with serve(harness_showing(**kinds), user=member) as client:
        hidden = await client.get("/v1/runs")
        start = await client.post("/v1/runs/full-cycle", json={"confirm": True})

    async with serve(harness_showing(**{**kinds, "specific_stock": EVERYONE}), user=member) as client:
        listed = await client.get("/v1/runs")
        other_kind = await client.post("/v1/runs/full-cycle", json={"confirm": True})

    assert (hidden.status_code, start.status_code, listed.status_code, other_kind.status_code) == (403, 403, 200, 403)


async def test_showing_sinopac_to_everyone_never_lets_a_user_past_the_real_brokers_own_refusal() -> None:
    async with serve(harness_showing(sinopac=True), user=(MEMBER.username, MEMBER_PASSWORD)) as client:
        account = await client.get("/v1/account/history", params={"broker": "shioaji"})
        brokers = [broker["broker"] for broker in (await client.get("/v1/account/brokers")).json()]

    assert (account.status_code, account.json()["code"], brokers) == (403, "real_broker_refused", ["mock"])


async def test_hiding_the_sinopac_account_refuses_its_reads_even_to_an_administrator_and_leaves_ordering_alone() -> None:
    async with serve(harness_showing(sinopac=True, sinopac_account=OFF)) as client:
        account = await client.get("/v1/account/history", params={"broker": "shioaji"})
        mock = await client.get("/v1/account/history")
        brokers = [broker["broker"] for broker in (await client.get("/v1/account/brokers")).json()]

    assert (account.status_code, account.json()["code"], mock.status_code) == (403, "feature_hidden", 200)
    assert brokers == ["mock", "shioaji"]


async def test_turning_sinopac_ordering_off_leaves_it_out_of_the_brokers_and_its_account_readable() -> None:
    async with serve(harness_showing(sinopac=True, sinopac_ordering=OFF)) as client:
        account = await client.get("/v1/account/history", params={"broker": "shioaji"})
        brokers = [broker["broker"] for broker in (await client.get("/v1/account/brokers")).json()]

    assert (account.status_code, brokers) == (200, ["mock"])


GATED: dict[tuple[str, str], frozenset[Feature]] = {
    ("GET", "/v1/market/breadth"): frozenset({Feature.MARKET_OVERVIEW}),
    ("GET", "/v1/rankings/latest"): frozenset({Feature.RANKING}),
    ("GET", "/v1/market/stocks/2330/financials"): frozenset({Feature.STOCK_PAGES}),
    ("GET", "/v1/watchlist"): frozenset({Feature.WATCHLIST}),
    ("GET", "/v1/valuation/market"): frozenset({Feature.VALUATION}),
    ("POST", "/v1/runs/full-cycle"): frozenset({Feature.FULL_CYCLE}),
    ("POST", "/v1/runs/specific-stocks"): frozenset({Feature.SPECIFIC_STOCK}),
    ("POST", "/v1/runs/buzz-scan"): frozenset({Feature.BUZZ}),
    ("POST", "/v1/runs/intraday"): frozenset({Feature.INTRADAY}),
    ("PUT", "/v1/technical-settings"): frozenset({Feature.STRATEGY_LIBRARY, Feature.STRATEGY_DESIGNER}),
    ("GET", "/v1/backtests"): frozenset({Feature.STRATEGY_BACKTEST}),
    ("GET", "/v1/account/history"): frozenset({Feature.MOCK_ACCOUNT}),
    ("GET", "/v1/account/history?broker=shioaji"): frozenset({Feature.SINOPAC_ACCOUNT}),
    ("POST", "/v1/runs/intraday?broker=shioaji"): frozenset({Feature.SINOPAC_ORDERING}),
    ("GET", "/v1/holdings"): frozenset({Feature.HOLDINGS}),
}
"""A route of each feature, with the features that must all be off before it hides: a strategy save belongs to two."""


def test_the_routes_checked_below_cover_every_feature() -> None:
    assert frozenset().union(*GATED.values()) == set(Feature)


@pytest.mark.parametrize(("method", "path"), GATED)
async def test_each_features_route_refuses_even_an_administrator_once_the_feature_is_off(method: str, path: str) -> None:
    hidden = {feature.value: OFF for feature in GATED[method, path]}

    async with serve(harness_showing(sinopac=True, **hidden)) as client:
        refused = await client.request(method, path, json={"confirm": True})

    async with serve(harness_showing(sinopac=True)) as client:
        shown = await client.request(method, path, json={"confirm": True})

    assert (refused.status_code, refused.json()["code"]) == (403, "feature_hidden")
    assert "feature_hidden" not in shown.text


STOCK_PAGE_READS = ("analysis", "news", "ranking")


@pytest.mark.parametrize(
    ("hidden", "as_member", "refused"),
    [
        ({}, True, []),
        ({"stock_pages": OFF}, False, ["analysis", "news", "ranking"]),
        ({"stock_pages": ADMINISTRATORS}, True, ["analysis", "news", "ranking"]),
        ({"ranking": OFF}, False, ["ranking"]),
        ({"ranking": ADMINISTRATORS}, True, ["ranking"]),
        ({"ranking": ADMINISTRATORS}, False, []),
    ],
)
async def test_a_stock_pages_reads_follow_the_stock_pages_and_its_score_needs_the_ranking_shown_too(
    hidden: dict[str, FeatureVisibility], as_member: bool, refused: list[str]
) -> None:
    user = (MEMBER.username, MEMBER_PASSWORD) if as_member else None

    async with serve(harness_showing(**hidden), **({"user": user} if user else {})) as client:
        answers = {read: await client.get(f"/v1/market/stocks/2330/{read}") for read in STOCK_PAGE_READS}

    assert [read for read, answer in answers.items() if answer.status_code == 403] == refused
    assert all(answers[read].json()["code"] == "feature_hidden" for read in refused)


async def test_a_visitor_reads_a_stock_page_only_where_everyone_sees_it_and_its_score_only_with_the_ranking() -> None:
    async with serve(harness_showing(ranking=ADMINISTRATORS), authorized=False) as visitor:
        answers = {read: await visitor.get(f"/v1/market/stocks/2330/{read}") for read in STOCK_PAGE_READS}

    assert [read for read, answer in answers.items() if "feature_hidden" in answer.text] == ["ranking"]
