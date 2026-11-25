"""
BrokerAccessRule and BuyLimitRule: which broker an order may reach at its send, and the limits of a real broker's BUYs
(the owner's I1 and I2). Each case is one refusal reason, or the order that passes.
"""

from dataclasses import replace
from datetime import datetime
from typing import Literal

import pytest
from support.settings import shipped_config

from a_domain.model.system.user import User
from a_domain.model.trading.order import Order
from a_domain.rules.trading.order_rule import BrokerLink, SiteOrdering
from a_domain.types.enums import (
    Audience,
    ExecutionProvider,
    FeatureVisibility,
    OrderStatus,
    OrderType,
    RejectReason,
    Role,
    ShioajiServer,
    TimeInForce,
    TradeAction,
    UserStatus,
    Workflow,
)
from a_domain.types.ids import UserId, new_decision_id, new_run_id
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

NOW = datetime(2026, 10, 19, 10, 20, tzinfo=TAIWAN_TIMEZONE)
ADMINISTRATOR = User(user_id=UserId("local"), username="hsiu", email="hsiu@example.com", role=Role.ADMINISTRATOR, created_at=NOW)
MEMBER = replace(ADMINISTRATOR, user_id=UserId("member"), username="member", email="member@example.com", role=Role.USER)
SINOPAC = BrokerLink(broker=ExecutionProvider.SHIOAJI, up=True, simulation=True)
MOCK = BrokerLink(broker=ExecutionProvider.MOCK)
SHIPPED = shipped_config()


RULE = SHIPPED.broker_access_rule()
"""The shipped settings: dev (SinoPac's simulation server), a personal site, a BUY at most 25% of the equity, a day's 110%."""

EQUITY = 400_000.0
"""The account as the run valued it: at the shipped shares, at most 100,000 a BUY and 440,000 of BUYs a day."""

SHIPPED_ORDERING = SiteOrdering(ordering=SHIPPED.features.ordering(), server=SHIPPED.shioaji.server)
"""What the shipped settings on disk say of SinoPac: nobody orders, on the simulation server."""

EVERYONE = SiteOrdering(ordering=dict.fromkeys(ExecutionProvider, FeatureVisibility.EVERYONE), server=ShioajiServer.SIMULATION)
"""Settings on disk that let everyone order on SinoPac's simulation server."""


def order(
    price: float = 500,
    quantity: int = 100,
    action: Literal[TradeAction.BUY, TradeAction.SELL] = TradeAction.BUY,
    status: OrderStatus = OrderStatus.PENDING,
    stock_id: str = "2330",
) -> Order:
    made = Order(
        run_id=new_run_id(),
        decision_id=new_decision_id(),
        stock_id=stock_id,
        action=action,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=price,
        price_at_signal=price,
        time_in_force=TimeInForce.IOC,
        created_at=NOW,
        updated_at=NOW,
    )

    if status != OrderStatus.PENDING:
        made.status = status

    return made


def refusal(
    sent: Order,
    run_broker: ExecutionProvider,
    link: BrokerLink,
    user: User | None,
    earlier: list[Order] | None = None,
    equity: float | None = EQUITY,
) -> str | None:
    """With the site's ordering switch on for everyone at the send, so each later check of a real broker shows its own reason."""
    reason = RULE.apply(sent, Workflow.MANUAL_BUY, run_broker, link, user, EVERYONE, earlier or [], equity)
    return reason[0].name if reason else None


def test_the_mock_account_takes_any_order_of_a_run_that_chose_it_from_anyone() -> None:
    assert refusal(order(price=5000, quantity=1000), ExecutionProvider.MOCK, MOCK, None) is None


@pytest.mark.parametrize("server", list(ShioajiServer))
@pytest.mark.parametrize("user", [ADMINISTRATOR, MEMBER, None], ids=["administrator", "member", "nobody"])
def test_the_shipped_settings_send_no_order_to_sinopac_whatever_the_server_and_the_user(
    server: ShioajiServer, user: User | None
) -> None:
    shipped = replace(SHIPPED_ORDERING, server=server)
    login = replace(SINOPAC, simulation=server.simulation)

    for sent in (order(), order(action=TradeAction.SELL)):
        assert RULE.apply(sent, Workflow.MANUAL_BUY, ExecutionProvider.SHIOAJI, login, user, shipped, [], EQUITY) == (
            RejectReason.ORDERING_OFF,
            "this site has ordering on shioaji off: features.sinopac_ordering",
        )

    assert SHIPPED_ORDERING.ordering[ExecutionProvider.SHIOAJI] == FeatureVisibility.OFF
    assert RULE.apply(order(), Workflow.MANUAL_BUY, ExecutionProvider.MOCK, MOCK, user, shipped, [], None) is None


def test_ordering_shown_to_administrators_refuses_a_member_at_the_switch_and_lets_an_administrator_through() -> None:
    administrators = replace(EVERYONE, ordering=EVERYONE.ordering | {ExecutionProvider.SHIOAJI: FeatureVisibility.ADMINISTRATORS})

    assert (
        RULE.apply(order(), Workflow.MANUAL_BUY, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, administrators, [], EQUITY) is None
    )

    for user in (MEMBER, None):
        refused = RULE.apply(order(), Workflow.MANUAL_BUY, ExecutionProvider.SHIOAJI, SINOPAC, user, administrators, [], EQUITY)
        assert refused is not None and refused[0] == RejectReason.ORDERING_OFF


def test_an_administrators_sinopac_buy_within_the_limits_passes() -> None:
    assert refusal(order(), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR) is None


@pytest.mark.parametrize(
    ("run_broker", "link", "user", "reason"),
    [
        (ExecutionProvider.MOCK, SINOPAC, ADMINISTRATOR, "BROKER_NOT_CHOSEN"),
        (ExecutionProvider.SHIOAJI, MOCK, ADMINISTRATOR, "BROKER_NOT_CHOSEN"),
        (ExecutionProvider.SHIOAJI, SINOPAC, MEMBER, "REAL_BROKER_REFUSED"),
        (ExecutionProvider.SHIOAJI, SINOPAC, replace(ADMINISTRATOR, status=UserStatus.DEACTIVATED), "REAL_BROKER_REFUSED"),
        (ExecutionProvider.SHIOAJI, SINOPAC, None, "REAL_BROKER_REFUSED"),
        (ExecutionProvider.SHIOAJI, replace(SINOPAC, up=False), ADMINISTRATOR, "BROKER_LOGIN_DOWN"),
        (ExecutionProvider.SHIOAJI, replace(SINOPAC, simulation=False), ADMINISTRATOR, "BROKER_SERVER_MISMATCH"),
    ],
    ids=["mock-run-to-sinopac", "sinopac-run-to-mock", "member", "deactivated", "nobody", "login-down", "production-login"],
)
def test_each_check_of_a_real_broker_refuses_with_its_reason(
    run_broker: ExecutionProvider, link: BrokerLink, user: User | None, reason: str
) -> None:
    assert refusal(order(), run_broker, link, user) == reason


def test_a_public_site_offers_no_real_broker() -> None:
    public = SHIPPED.model_copy(update={"audience": Audience.PUBLIC}).broker_access_rule()

    assert public.apply(order(), Workflow.MANUAL_BUY, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, EVERYONE, [], EQUITY) == (
        RejectReason.BROKER_NOT_OFFERED,
        "this site orders on mock only, not shioaji",
    )


@pytest.mark.parametrize("named", [*ShioajiServer, None], ids=[*ShioajiServer, "settings-that-do-not-load"])
@pytest.mark.parametrize("login", list(ShioajiServer))
def test_a_sinopac_order_goes_only_to_a_login_on_the_server_the_settings_on_disk_name_at_the_send(
    login: ShioajiServer, named: ShioajiServer | None
) -> None:
    """
    The server comes from the same read of the settings on disk as the switch, not from the settings the run started
    on: a run that started on one server and whose login is still there is refused once the files name the other one,
    with ordering on for everyone.
    """
    link, on_disk = replace(SINOPAC, simulation=login.simulation), replace(EVERYONE, server=named) if named is not None else None
    refused = RULE.apply(order(), Workflow.MANUAL_BUY, ExecutionProvider.SHIOAJI, link, ADMINISTRATOR, on_disk, [], EQUITY)

    if named == login:
        assert refused is None
    elif named is None:
        assert refused == (RejectReason.ORDERING_OFF, "the settings files on disk do not load, so this site lets nobody order")
    else:
        assert refused == (
            RejectReason.BROKER_SERVER_MISMATCH,
            f"the shioaji login is not on the {named.value} server shioaji.server names on disk now",
        )


def test_a_sinopac_buy_above_the_order_limit_is_refused_and_one_at_it_passes() -> None:
    above = RULE.apply(
        order(price=1005, quantity=100), Workflow.MANUAL_BUY, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, EVERYONE, [], EQUITY
    )

    assert above == (
        RejectReason.ORDER_VALUE_LIMIT,
        "costs 100,500 at its limit, above 100,000: trading.max_order_equity_pct 25% of the equity 400,000",
    )
    assert refusal(order(price=1000, quantity=100), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR) is None


@pytest.mark.parametrize(("equity", "passes"), [(400_000, True), (800_000, True), (399_000, False), (200_000, False)])
def test_the_order_limit_follows_the_equity_the_run_valued_up_and_down(equity: float, passes: bool) -> None:
    """A BUY of 100,000 at its limit: within 25% of an account of 400,000 or more, past it once the account shrank."""
    reason = refusal(order(price=1000, quantity=100), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, equity=equity)

    assert reason == (None if passes else "ORDER_VALUE_LIMIT")


def test_a_sinopac_buy_of_a_run_that_valued_no_account_is_refused_and_a_mock_one_needs_none() -> None:
    assert RULE.apply(order(), Workflow.FOLLOW, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, EVERYONE, [], None) == (
        RejectReason.ORDER_VALUE_LIMIT,
        "its run valued no account to derive trading.max_order_equity_pct and trading.max_daily_buy_equity_pct from",
    )
    assert refusal(order(), ExecutionProvider.MOCK, MOCK, None, equity=None) is None


def earlier_today(filled: int = 140) -> list[Order]:
    """380,000 the day's earlier BUYs may have bought, with `filled` = 140: each counts as BuyLimitRule counts it."""
    return [
        order(price=1000, quantity=100, status=OrderStatus.SUBMITTED, stock_id="2317"),
        order(price=1000, quantity=100, status=OrderStatus.FAILED),
        order(price=1000, quantity=100, status=OrderStatus.REJECTED),
        replace(order(price=1000, quantity=100, status=OrderStatus.CANCELLED), filled_quantity=40),
        replace(order(price=1000, quantity=filled, status=OrderStatus.FILLED, stock_id="1101"), filled_quantity=filled),
    ]


def test_the_days_earlier_buys_count_what_each_may_have_bought() -> None:
    earlier = earlier_today()
    sent = order(price=1000, quantity=60)

    assert refusal(sent, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, earlier) is None
    assert refusal(order(price=1000, quantity=61), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, earlier) == "DAILY_BUY_LIMIT"


@pytest.mark.parametrize(("equity", "shares", "reason"), [(400_000, 60, None), (380_000, 60, "DAILY_BUY_LIMIT"), (600_000, 150, None)])
def test_the_days_limit_follows_the_equity_the_run_valued_up_and_down(equity: float, shares: int, reason: str | None) -> None:
    """After 380,000 of BUYs: 110% of 400,000 leaves 60,000, of 380,000 18,000, and of 600,000 280,000."""
    sent = order(price=1000, quantity=shares)

    assert refusal(sent, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, earlier_today(), equity=equity) == reason


def test_an_unconfirmed_earlier_buy_counts_in_full_whatever_it_recorded_filled() -> None:
    unconfirmed = [
        replace(order(price=1000, quantity=100, status=OrderStatus.UNCONFIRMED, stock_id="2317"), filled_quantity=40) for _ in range(2)
    ]
    filled = replace(order(price=1000, quantity=140, status=OrderStatus.FILLED, stock_id="1101"), filled_quantity=140)
    earlier = [*unconfirmed, replace(order(price=1000, quantity=100, status=OrderStatus.CANCELLED), filled_quantity=1), filled]

    assert refusal(order(price=1000, quantity=99), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, earlier) is None
    assert refusal(order(price=1000, quantity=100), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, earlier) == "DAILY_BUY_LIMIT"


@pytest.mark.parametrize("open_status", [OrderStatus.UNCONFIRMED, OrderStatus.SUBMITTED, OrderStatus.PENDING])
def test_a_buy_of_a_stock_an_earlier_buy_of_which_is_still_open_is_refused_since_both_may_deal(open_status: OrderStatus) -> None:
    """
    An earlier BUY still PENDING or SUBMITTED is one a process that stopped left, before the Web API's timer ended its
    run, or one another run sends at this moment: it may deal as much as one that awaits settlement.
    """
    earlier = order(price=100, quantity=100, status=open_status)
    settled = replace(order(price=100, quantity=100, status=OrderStatus.CANCELLED), filled_quantity=40)

    assert RULE.apply(
        order(), Workflow.MANUAL_BUY, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, EVERYONE, [earlier], EQUITY
    ) == (
        RejectReason.UNSETTLED_BUY,
        f"order {earlier.id}, an earlier BUY of 2330 today, is {open_status.value} and may still deal: another BUY of 2330 "
        "waits until it ends or the broker's record of the day settles it",
    )
    assert refusal(order(stock_id="2317"), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, [earlier]) is None
    assert refusal(order(), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, [settled]) is None
    assert refusal(order(action=TradeAction.SELL), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, [earlier]) is None


def test_the_order_being_sent_is_not_counted_twice_when_the_journal_already_holds_it() -> None:
    sent = order(price=1000, quantity=100)
    earlier = [order(price=1000, quantity=100, status=OrderStatus.FILLED) for _ in range(3)]
    earlier = [replace(each, filled_quantity=100) for each in earlier]

    assert refusal(sent, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, [*earlier, sent]) is None


def test_a_sinopac_sell_is_never_held_to_the_limits() -> None:
    sell = order(price=5000, quantity=1000, action=TradeAction.SELL)
    spent = [replace(order(price=1000, quantity=100, status=OrderStatus.FILLED), filled_quantity=100) for _ in range(3)]

    assert refusal(sell, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, spent) is None
