from datetime import date, datetime, timedelta

import pytest
from support.settings import shipped_config

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.collect.freshness import DataFreshnessRule
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.order_rule import OrderRule
from a_domain.types.enums import OrderPricing, OrderStatus, OrderType, SignalSource, TimeInForce, TradeAction, TradingPhase
from a_domain.types.ids import new_run_id
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

NOW = datetime(2026, 10, 19, 10, 20, tzinfo=TAIWAN_TIMEZONE)
COSTS = TradingCostRule(
    fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20, bond_etf_tax_exempt_until=date(2026, 12, 31)
)
LIMIT_PRICE = shipped_config().limit_price_rule()


LAST_CLOSE = datetime(2026, 10, 16, 13, 30, tzinfo=TAIWAN_TIMEZONE)
"""Friday's close: on Monday 10:20 the close of the last closed session."""


def order_rule(pricing: OrderPricing = OrderPricing.REALTIME_QUOTE) -> OrderRule:
    return OrderRule(pricing=pricing, price_freshness=DataFreshnessRule(timedelta(minutes=15)), limit_price_rule=LIMIT_PRICE)


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


@pytest.mark.parametrize(("action", "limit"), [(TradeAction.BUY, 102), (TradeAction.SELL, 98)], ids=["buy", "sell"])
def test_a_fresh_decision_becomes_a_pending_ioc_order_marketable_up_to_two_percent_past_its_price(
    action: TradeAction, limit: float
) -> None:
    signal = signal_at(NOW - timedelta(minutes=15), action=action)
    run_id = new_run_id()

    order = RULE.apply(signal, run_id, now=NOW, phase=TradingPhase.CONTINUOUS, last_close=LAST_CLOSE)

    assert (order.status, order.order_type, order.time_in_force) == (OrderStatus.PENDING, OrderType.LIMIT, TimeInForce.IOC)
    assert (order.limit_price, order.price_at_signal, order.quantity) == (limit, 100, 1000)
    assert (order.run_id, order.decision_id) == (run_id, signal.decision_id)


@pytest.mark.parametrize(
    ("phase", "quote_age", "reason"),
    [
        (TradingPhase.CLOSED, 1, "MARKET_CLOSED"),
        (TradingPhase.OPENING_AUCTION, 1, "MARKET_CLOSED"),
        (TradingPhase.CLOSING_AUCTION, 1, "MARKET_CLOSED"),
        (TradingPhase.CONTINUOUS, 16, "STALE_PRICE"),
    ],
)
def test_each_gate_rejects_with_its_reason(phase: TradingPhase, quote_age: int, reason: str) -> None:
    order = RULE.apply(
        buy_signal(quoted_at=NOW - timedelta(minutes=quote_age)), new_run_id(), now=NOW, phase=phase, last_close=LAST_CLOSE
    )

    assert order.status == OrderStatus.REJECTED
    assert order.reason is not None and order.reason.startswith(f"{reason}: ")


def test_a_quote_fresh_when_fetched_is_refused_once_it_aged_past_the_limit() -> None:
    signal = buy_signal(quoted_at=datetime(2026, 10, 19, 9, 59, tzinfo=TAIWAN_TIMEZONE))

    assert RULE.apply(
        signal, new_run_id(), now=signal.price_observed_at + timedelta(minutes=1), phase=TradingPhase.CONTINUOUS, last_close=LAST_CLOSE
    ).status == (OrderStatus.PENDING)
    assert RULE.apply(signal, new_run_id(), now=NOW, phase=TradingPhase.CONTINUOUS, last_close=LAST_CLOSE).reason == (
        "STALE_PRICE: price 100.00 was quoted at 2026-10-19 09:59, 21 min before 10:20; the limit is 15 min"
    )


@pytest.mark.parametrize(
    ("action", "yahoo_quote", "exchange_price", "limit"),
    [(TradeAction.BUY, 28.399999618530273, 28.4, 28.95), (TradeAction.SELL, 28.350000381469727, 28.35, 27.8)],
    ids=["buy", "sell"],
)
def test_an_order_priced_from_a_float32_quote_is_capped_from_its_tick_and_takes_an_exchange_fill_at_that_price(
    action: TradeAction, yahoo_quote: float, exchange_price: float, limit: float
) -> None:
    order = RULE.apply(
        signal_at(NOW, yahoo_quote, action), new_run_id(), now=NOW, phase=TradingPhase.CONTINUOUS, last_close=LAST_CLOSE
    )

    order.submit(now=NOW)
    cost = COSTS.apply(action, "2330", exchange_price, 1000, now=NOW)
    order.fill(1000, exchange_price, cost.fee, cost.tax, now=NOW)

    assert (order.status, repr(order.limit_price), order.average_filled_price) == (OrderStatus.FILLED, repr(limit), exchange_price)


def close_signal(session_close: datetime, price: float = 77) -> TradeSignal:
    """A decision priced at an official close: a stock whose latest bar is that session's daily bar."""
    stock = Stock(stock_id="2330", ohlcv=[Ohlcv(ts=session_close, open=price, high=price, low=price, close=price, volume=10)])
    return TradeSignal.of(stock, action=TradeAction.BUY, source=SignalSource.FOLLOW, score=90, reason="test", quantity=1000, now=NOW)


SATURDAY = datetime(2026, 10, 17, 10, 0, tzinfo=TAIWAN_TIMEZONE)


def test_an_official_close_prices_a_mock_order_while_no_session_trades() -> None:
    rule = order_rule(pricing=OrderPricing.OFFICIAL_CLOSE)

    order = rule.apply(close_signal(LAST_CLOSE), new_run_id(), now=SATURDAY, phase=TradingPhase.CLOSED, last_close=LAST_CLOSE)

    assert (order.status, order.limit_price, order.price_at_signal, order.time_in_force) == (
        OrderStatus.PENDING,
        78.5,
        77,
        TimeInForce.IOC,
    )


@pytest.mark.parametrize(
    ("phase", "priced_at", "reason"),
    [
        (TradingPhase.CONTINUOUS, LAST_CLOSE, "SESSION_IN_PROGRESS"),
        (TradingPhase.OPENING_AUCTION, LAST_CLOSE, "SESSION_IN_PROGRESS"),
        (TradingPhase.CLOSING_AUCTION, LAST_CLOSE, "SESSION_IN_PROGRESS"),
        (TradingPhase.CLOSED, LAST_CLOSE - timedelta(days=1), "STALE_PRICE"),
    ],
    ids=["continuous", "opening-auction", "closing-auction", "older-close"],
)
def test_an_official_close_is_refused_during_a_session_and_when_older_than_the_last_close(
    phase: TradingPhase, priced_at: datetime, reason: str
) -> None:
    rule = order_rule(OrderPricing.OFFICIAL_CLOSE)

    order = rule.apply(close_signal(priced_at), new_run_id(), now=SATURDAY, phase=phase, last_close=LAST_CLOSE)

    assert order.status == OrderStatus.REJECTED
    assert order.reason is not None and order.reason.startswith(f"{reason}: ")


def test_a_daily_close_never_prices_a_realtime_order() -> None:
    order = RULE.apply(close_signal(LAST_CLOSE), new_run_id(), now=NOW, phase=TradingPhase.CONTINUOUS, last_close=LAST_CLOSE)

    assert order.reason is not None and order.reason.startswith("STALE_PRICE: ")
