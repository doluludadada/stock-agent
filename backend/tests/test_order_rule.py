from datetime import date, datetime, timedelta

import pytest
from support.settings import shipped_config

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.collect.freshness import DataFreshnessRule
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.order_rule import OrderGateRule, OrderRule
from a_domain.types.enums import (
    ExecutionProvider,
    OrderMode,
    OrderStatus,
    OrderType,
    SignalSource,
    TimeInForce,
    TradeAction,
    TradingPhase,
)
from a_domain.types.ids import new_run_id
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

NOW = datetime(2026, 10, 19, 10, 20, tzinfo=TAIWAN_TIMEZONE)
COSTS = TradingCostRule(
    fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20, bond_etf_tax_exempt_until=date(2026, 12, 31)
)
LIMIT_PRICE = shipped_config().market.limit_price_rule()


def order_rule(order_mode: OrderMode = OrderMode.MOCK_ONLY, provider: ExecutionProvider = ExecutionProvider.MOCK) -> OrderRule:
    gate_rule = OrderGateRule(
        order_mode=order_mode, execution_provider=provider, price_freshness=DataFreshnessRule(timedelta(minutes=15))
    )
    return OrderRule(gate_rule=gate_rule, limit_price_rule=LIMIT_PRICE)


RULE = order_rule()


def signal_at(quoted_at: datetime, price: float = 100, action: TradeAction = TradeAction.BUY) -> TradeSignal:
    stock = Stock(
        stock_id="2330",
        realtime_bar=Ohlcv(ts=quoted_at, open=price, high=price, low=price, close=price, volume=10),
        composite_score=90,
    )
    return TradeSignal.of(stock, action=action, source=SignalSource.COMBINED, score=90, reason="test", quantity=1000, now=quoted_at)


def buy_signal(quoted_at: datetime) -> TradeSignal:
    return signal_at(quoted_at)


def test_a_fresh_decision_becomes_a_pending_ioc_limit_order_at_its_price() -> None:
    signal = buy_signal(quoted_at=NOW - timedelta(minutes=15))
    run_id = new_run_id()

    order = RULE.apply(signal, run_id, now=NOW, phase=TradingPhase.CONTINUOUS)

    assert (order.status, order.order_type, order.time_in_force) == (OrderStatus.PENDING, OrderType.LIMIT, TimeInForce.IOC)
    assert (order.limit_price, order.quantity, order.run_id, order.decision_id) == (100, 1000, run_id, signal.decision_id)


@pytest.mark.parametrize(
    ("order_mode", "provider", "phase", "quote_age", "reason"),
    [
        (OrderMode.DISABLED, ExecutionProvider.MOCK, TradingPhase.CONTINUOUS, 1, "ORDER_MODE_DISABLED"),
        (OrderMode.MOCK_ONLY, ExecutionProvider.SHIOAJI, TradingPhase.CONTINUOUS, 1, "ORDER_MODE_MISMATCH"),
        (OrderMode.LIVE, ExecutionProvider.MOCK, TradingPhase.CONTINUOUS, 1, "ORDER_MODE_MISMATCH"),
        (OrderMode.MOCK_ONLY, ExecutionProvider.MOCK, TradingPhase.CLOSED, 1, "MARKET_CLOSED"),
        (OrderMode.MOCK_ONLY, ExecutionProvider.MOCK, TradingPhase.OPENING_AUCTION, 1, "MARKET_CLOSED"),
        (OrderMode.MOCK_ONLY, ExecutionProvider.MOCK, TradingPhase.CLOSING_AUCTION, 1, "MARKET_CLOSED"),
        (OrderMode.MOCK_ONLY, ExecutionProvider.MOCK, TradingPhase.CONTINUOUS, 16, "STALE_PRICE"),
    ],
)
def test_each_gate_rejects_with_its_reason(
    order_mode: OrderMode, provider: ExecutionProvider, phase: TradingPhase, quote_age: int, reason: str
) -> None:
    rule = order_rule(order_mode, provider)

    order = rule.apply(buy_signal(quoted_at=NOW - timedelta(minutes=quote_age)), new_run_id(), now=NOW, phase=phase)

    assert order.status == OrderStatus.REJECTED
    assert order.reason is not None and order.reason.startswith(f"{reason}: ")


def test_a_quote_fresh_when_fetched_is_refused_once_it_aged_past_the_limit() -> None:
    signal = buy_signal(quoted_at=datetime(2026, 10, 19, 9, 59, tzinfo=TAIWAN_TIMEZONE))

    assert RULE.apply(
        signal, new_run_id(), now=signal.price_observed_at + timedelta(minutes=1), phase=TradingPhase.CONTINUOUS
    ).status == (OrderStatus.PENDING)
    assert RULE.apply(signal, new_run_id(), now=NOW, phase=TradingPhase.CONTINUOUS).reason == (
        "STALE_PRICE: price 100.00 was quoted at 2026-10-19 09:59, 21 min before 10:20; the limit is 15 min"
    )


@pytest.mark.parametrize(
    ("action", "yahoo_quote", "exchange_price"),
    [(TradeAction.BUY, 28.399999618530273, 28.4), (TradeAction.SELL, 28.350000381469727, 28.35)],
    ids=["buy", "sell"],
)
def test_an_order_priced_from_a_float32_quote_takes_an_exchange_fill_at_that_price(
    action: TradeAction, yahoo_quote: float, exchange_price: float
) -> None:
    order = RULE.apply(signal_at(NOW, yahoo_quote, action), new_run_id(), now=NOW, phase=TradingPhase.CONTINUOUS)

    order.submit(now=NOW)
    order.fill(1000, exchange_price, COSTS.apply(action, "2330", exchange_price, 1000, now=NOW), now=NOW)

    assert (order.status, repr(order.limit_price)) == (OrderStatus.FILLED, repr(exchange_price))
