from datetime import datetime, timedelta

import pytest

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.collect.freshness import DataFreshnessRule
from a_domain.rules.trading.order_rule import OrderRule
from a_domain.types.enums import ExecutionProvider, OrderMode, OrderStatus, OrderType, SignalSource, TimeInForce, TradeAction
from a_domain.types.ids import new_run_id
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

NOW = datetime(2026, 10, 19, 10, 20, tzinfo=TAIWAN_TIMEZONE)
RULE = OrderRule(
    order_mode=OrderMode.MOCK_ONLY, execution_provider=ExecutionProvider.MOCK, price_freshness=DataFreshnessRule(timedelta(minutes=15))
)


def buy_signal(quoted_at: datetime) -> TradeSignal:
    stock = Stock(
        stock_id="2330", realtime_bar=Ohlcv(ts=quoted_at, open=100, high=100, low=100, close=100, volume=10), composite_score=90
    )
    return TradeSignal.of(stock, action=TradeAction.BUY, source=SignalSource.COMBINED, score=90, reason="test", quantity=1000)


def test_a_fresh_decision_becomes_a_pending_ioc_limit_order_at_its_price() -> None:
    signal = buy_signal(quoted_at=NOW - timedelta(minutes=15))
    run_id = new_run_id()

    order = RULE.order_for(signal, run_id, now=NOW, market_open=True)

    assert (order.status, order.order_type, order.time_in_force) == (OrderStatus.PENDING, OrderType.LIMIT, TimeInForce.IOC)
    assert (order.limit_price, order.quantity, order.run_id, order.decision_id) == (100, 1000, run_id, signal.decision_id)


@pytest.mark.parametrize(
    ("order_mode", "provider", "market_open", "quote_age", "reason"),
    [
        (OrderMode.DISABLED, ExecutionProvider.MOCK, True, 1, "ORDER_MODE_DISABLED"),
        (OrderMode.MOCK_ONLY, ExecutionProvider.SHIOAJI, True, 1, "ORDER_MODE_MISMATCH"),
        (OrderMode.LIVE, ExecutionProvider.MOCK, True, 1, "ORDER_MODE_MISMATCH"),
        (OrderMode.MOCK_ONLY, ExecutionProvider.MOCK, False, 1, "MARKET_CLOSED"),
        (OrderMode.MOCK_ONLY, ExecutionProvider.MOCK, True, 16, "STALE_PRICE"),
    ],
)
def test_each_gate_rejects_with_its_reason(
    order_mode: OrderMode, provider: ExecutionProvider, market_open: bool, quote_age: int, reason: str
) -> None:
    rule = OrderRule(order_mode=order_mode, execution_provider=provider, price_freshness=DataFreshnessRule(timedelta(minutes=15)))

    order = rule.order_for(buy_signal(quoted_at=NOW - timedelta(minutes=quote_age)), new_run_id(), now=NOW, market_open=market_open)

    assert order.status == OrderStatus.REJECTED
    assert order.reason is not None and order.reason.startswith(f"{reason}: ")


def test_a_quote_fresh_when_fetched_is_refused_once_it_aged_past_the_limit() -> None:
    signal = buy_signal(quoted_at=datetime(2026, 10, 19, 9, 59, tzinfo=TAIWAN_TIMEZONE))

    assert RULE.order_for(signal, new_run_id(), now=signal.price_observed_at + timedelta(minutes=1), market_open=True).status == (
        OrderStatus.PENDING
    )
    assert RULE.order_for(signal, new_run_id(), now=NOW, market_open=True).reason == (
        "STALE_PRICE: price 100.00 was quoted at 2026-10-19 09:59, 21 min before 10:20; the limit is 15 min"
    )
