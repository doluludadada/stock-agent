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
from a_domain.rules.trading.order_rule import BrokerLink
from a_domain.types.enums import (
    Audience,
    ExecutionProvider,
    OrderStatus,
    OrderType,
    RejectReason,
    Role,
    SystemEnvironment,
    TimeInForce,
    TradeAction,
    UserStatus,
)
from a_domain.types.ids import UserId, new_decision_id, new_run_id
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

NOW = datetime(2026, 10, 19, 10, 20, tzinfo=TAIWAN_TIMEZONE)
ADMINISTRATOR = User(user_id=UserId("local"), username="hsiu", email="hsiu@example.com", role=Role.ADMINISTRATOR, created_at=NOW)
MEMBER = replace(ADMINISTRATOR, user_id=UserId("member"), username="member", email="member@example.com", role=Role.USER)
SINOPAC = BrokerLink(broker=ExecutionProvider.SHIOAJI, up=True, simulation=True)
MOCK = BrokerLink(broker=ExecutionProvider.MOCK)
RULE = shipped_config().broker_access_rule()
"""The shipped settings: dev (SinoPac's simulation server), a personal site, at most 100,000 a BUY and 300,000 a day."""


def order(
    price: float = 500,
    quantity: int = 100,
    action: Literal[TradeAction.BUY, TradeAction.SELL] = TradeAction.BUY,
    status: OrderStatus = OrderStatus.PENDING,
) -> Order:
    made = Order(
        run_id=new_run_id(),
        decision_id=new_decision_id(),
        stock_id="2330",
        action=action,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=price,
        time_in_force=TimeInForce.IOC,
        created_at=NOW,
        updated_at=NOW,
    )

    if status != OrderStatus.PENDING:
        made.status = status

    return made


def refusal(
    sent: Order, run_broker: ExecutionProvider, link: BrokerLink, user: User | None, earlier: list[Order] | None = None
) -> str | None:
    reason = RULE.apply(sent, run_broker, link, user, earlier or [])
    return reason[0].name if reason else None


def test_the_mock_account_takes_any_order_of_a_run_that_chose_it_from_anyone() -> None:
    assert refusal(order(price=5000, quantity=1000), ExecutionProvider.MOCK, MOCK, None) is None


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
    ids=["mock-run-to-sinopac", "sinopac-run-to-mock", "member", "deactivated", "nobody", "login-down", "production-login-in-dev"],
)
def test_each_check_of_a_real_broker_refuses_with_its_reason(
    run_broker: ExecutionProvider, link: BrokerLink, user: User | None, reason: str
) -> None:
    assert refusal(order(), run_broker, link, user) == reason


def test_a_public_site_offers_no_real_broker_and_prod_trades_on_the_real_account_only() -> None:
    shipped = shipped_config()
    public = shipped.model_copy(update={"audience": Audience.PUBLIC}).broker_access_rule()
    prod = shipped.model_copy(update={"environment": SystemEnvironment.PROD}).broker_access_rule()
    production = replace(SINOPAC, simulation=False)

    assert public.apply(order(), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, []) == (
        RejectReason.BROKER_NOT_OFFERED,
        "this site orders on mock only, not shioaji",
    )
    assert (prod.apply(order(), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, []) or ("",))[
        0
    ] == RejectReason.BROKER_SERVER_MISMATCH
    assert prod.apply(order(), ExecutionProvider.SHIOAJI, production, ADMINISTRATOR, []) is None


def test_a_sinopac_buy_above_the_order_limit_is_refused_and_one_at_it_passes() -> None:
    assert refusal(order(price=1005, quantity=100), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR) == "ORDER_VALUE_LIMIT"
    assert refusal(order(price=1000, quantity=100), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR) is None


def test_a_sinopac_buy_without_a_limit_price_is_refused_since_the_limits_cannot_value_it() -> None:
    market = replace(order(), order_type=OrderType.MARKET, limit_price=None)

    assert RULE.apply(market, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, []) == (
        RejectReason.ORDER_VALUE_LIMIT,
        "has no limit price to value against trading.max_order_value and trading.max_daily_buy_value",
    )
    assert refusal(market, ExecutionProvider.MOCK, MOCK, None) is None


def test_the_days_earlier_buys_count_what_each_may_have_bought() -> None:
    earlier = [
        order(price=1000, quantity=100, status=OrderStatus.SUBMITTED),
        order(price=1000, quantity=100, status=OrderStatus.FAILED),
        order(price=1000, quantity=100, status=OrderStatus.REJECTED),
        replace(order(price=1000, quantity=100, status=OrderStatus.CANCELLED), filled_quantity=40),
    ]
    sent = order(price=1000, quantity=60)

    assert refusal(sent, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, earlier) is None
    assert refusal(order(price=1000, quantity=61), ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, earlier) == "DAILY_BUY_LIMIT"


def test_the_order_being_sent_is_not_counted_twice_when_the_journal_already_holds_it() -> None:
    sent = order(price=1000, quantity=100)
    earlier = [order(price=1000, quantity=100, status=OrderStatus.FILLED) for _ in range(2)]
    earlier = [replace(each, filled_quantity=100) for each in earlier]

    assert refusal(sent, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, [*earlier, sent]) is None


def test_a_sinopac_sell_is_never_held_to_the_limits() -> None:
    sell = order(price=5000, quantity=1000, action=TradeAction.SELL)
    spent = [replace(order(price=1000, quantity=100, status=OrderStatus.FILLED), filled_quantity=100) for _ in range(3)]

    assert refusal(sell, ExecutionProvider.SHIOAJI, SINOPAC, ADMINISTRATOR, spent) is None
