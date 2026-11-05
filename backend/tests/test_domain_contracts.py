from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError
from support.trading_rules import EXIT_REASON, entry_rule, sizing_rule

from a_domain.model.trading.account import Account, Position
from a_domain.model.trading.order import Order
from a_domain.rules.scoring import CompositeScoreRule
from a_domain.rules.technical.calculation.calculator import MacdIndicator, MovingAverageIndicator
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.rules.trading.exit import StopLossRule
from a_domain.types.enums import IndicatorKind, OrderStatus, OrderType, TimeInForce, TradeAction
from a_domain.types.ids import new_decision_id, new_run_id

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)

COSTS = TradingCostRule(
    fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20, bond_etf_tax_exempt_until=date(2026, 12, 31)
)


def limit_order(action: TradeAction = TradeAction.BUY) -> Order:
    return Order(
        run_id=new_run_id(),
        decision_id=new_decision_id(),
        stock_id="2330",
        action=action,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.IOC,
        quantity=1,
        limit_price=100,
        created_at=NOW,
        updated_at=NOW,
    )


def test_trading_rules_reject_invalid_config() -> None:
    with pytest.raises(ValidationError):
        sizing_rule(risk_per_trade_pct=0)

    with pytest.raises(ValidationError):
        StopLossRule(stop_loss_pct=0, reason_rule=EXIT_REASON)


def test_indicators_reject_invalid_periods() -> None:
    with pytest.raises(ValidationError):
        MovingAverageIndicator(kind=IndicatorKind.SMA, period=0)

    with pytest.raises(ValidationError):
        MacdIndicator(kind=IndicatorKind.MACD, fast=26, slow=26, signal=9)


def test_entry_rule_rejects_invalid_threshold() -> None:
    with pytest.raises(ValidationError):
        entry_rule(buy_threshold=101)


def test_sizing_rule_rejects_invalid_price() -> None:
    with pytest.raises(ValidationError):
        sizing_rule(risk_per_trade_pct=0.02).apply(account=Account(cash=1000), equity=1000, stock_id="2330", price=0, now=NOW)


def test_composite_rule_rejects_zero_total_weight() -> None:
    with pytest.raises(ValidationError):
        CompositeScoreRule(technical_weight=0, ai_weight=0)


def test_order_submit_moves_pending_order_to_submitted() -> None:
    order = limit_order()

    order.submit(now=NOW)

    assert order.status == OrderStatus.SUBMITTED
    assert order.reason is None


def test_order_rejects_hold_submission() -> None:
    with pytest.raises(ValueError, match="action"):
        limit_order(action=TradeAction.HOLD)


def test_order_fill_applies_limit_price_rules() -> None:
    order = limit_order()
    order.submit(now=NOW)

    with pytest.raises(ValueError, match="BUY fill price cannot exceed limit_price"):
        cost = COSTS.apply(TradeAction.BUY, "2330", 101, 1, now=NOW)
        order.fill(1, 101, cost.fee, cost.tax, now=NOW)

    cost = COSTS.apply(TradeAction.BUY, "2330", 99, 1, now=NOW)
    order.fill(1, 99, cost.fee, cost.tax, now=NOW)

    assert order.status == OrderStatus.FILLED
    assert order.average_filled_price == 99


def test_order_requires_reason_for_terminal_failures() -> None:
    order = limit_order()

    with pytest.raises(ValueError, match="Failed order requires a reason"):
        order.fail(" ", now=NOW)


def test_position_add_recalculates_average_cost() -> None:
    position = Position(stock_id="2330", quantity=10, average_cost=100)

    position.add(quantity=5, price=130)

    assert position.quantity == 15
    assert position.average_cost == pytest.approx(110)


def test_position_reduce_keeps_active_position_positive() -> None:
    position = Position(stock_id="2330", quantity=10, average_cost=100)

    position.reduce(4)

    assert position.quantity == 6
    assert position.remaining_after_sell(6) == 0


def test_position_rejects_oversell() -> None:
    position = Position(stock_id="2330", quantity=10, average_cost=100)

    with pytest.raises(ValueError, match="Position quantity is insufficient"):
        position.remaining_after_sell(11)


def test_account_buy_updates_cash_and_position() -> None:
    position = Position(stock_id="2330", quantity=10, average_cost=100)
    account = Account(cash=1000, positions=[position])

    updated_position = account.buy(stock_id="2330", quantity=5, price=130, total_cost=650)

    assert account.cash == 350
    assert updated_position.quantity == 15
    assert updated_position.average_cost == pytest.approx(110)
    assert account.position_for("2330") is position


def test_account_buy_creates_new_position() -> None:
    account = Account(cash=1000)

    position = account.buy(stock_id="2330", quantity=5, price=100, total_cost=500)

    assert account.cash == 500
    assert account.position_for("2330") is position
    assert position.quantity == 5
    assert position.average_cost == 100


def test_account_sell_updates_cash_and_removes_closed_position() -> None:
    account = Account(cash=1000, positions=[Position(stock_id="2330", quantity=10, average_cost=100)])

    remaining_quantity = account.sell(stock_id="2330", quantity=10, cash_delta=950)

    assert remaining_quantity == 0
    assert account.cash == 1950
    assert account.position_for("2330") is None


def test_account_rejects_missing_sell_position() -> None:
    account = Account(cash=1000)

    with pytest.raises(ValueError, match="Position not found"):
        account.sell(stock_id="2330", quantity=1, cash_delta=100)
