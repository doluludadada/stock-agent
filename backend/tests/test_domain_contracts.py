import pytest
from icontract.errors import ViolationError

from a_domain.model.indicators.technical_indicators import MovingAverages
from a_domain.model.trading.account import Account
from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.rules.scoring import CompositeScoreRule
from a_domain.rules.technical.criteria.trend import MaAlignmentCriterion, PriceAboveMaCriterion
from a_domain.rules.trading import EntryRule, ExitRule, SizingRule
from a_domain.types.enums import OrderStatus, OrderType, TradeAction


def test_moving_averages_require_positive_periods() -> None:
    with pytest.raises(ViolationError):
        MovingAverages(price_ma={0: 100.0})

    with pytest.raises(ViolationError):
        MovingAverages(price_ma={20: 0})


def test_trading_rules_reject_invalid_config() -> None:
    rule = SizingRule(risk_per_trade_pct=0, stop_loss_pct=0.10, lot_size=1)
    with pytest.raises(ViolationError):
        rule.calculate(account=Account(cash=1000), price=10)

    with pytest.raises(ViolationError):
        ExitRule(stop_loss_pct=0, sell_threshold=30)


def test_technical_criteria_reject_invalid_periods() -> None:
    with pytest.raises(ViolationError):
        PriceAboveMaCriterion(0)

    with pytest.raises(ViolationError):
        MaAlignmentCriterion(20, 20)


def test_entry_rule_rejects_invalid_threshold() -> None:
    sizing_rule = SizingRule(risk_per_trade_pct=0.02, stop_loss_pct=0.10, lot_size=1)

    with pytest.raises(ViolationError):
        EntryRule(buy_threshold=101, sizing_rule=sizing_rule)


def test_sizing_rule_rejects_invalid_price() -> None:
    sizing_rule = SizingRule(risk_per_trade_pct=0.02, stop_loss_pct=0.10, lot_size=1)

    with pytest.raises(ViolationError):
        sizing_rule.calculate(account=Account(cash=1000), price=0)


def test_composite_rule_rejects_zero_total_weight() -> None:
    with pytest.raises(ViolationError):
        CompositeScoreRule(technical_weight=0, sentiment_weight=0)


def test_order_submit_moves_pending_order_to_submitted() -> None:
    order = Order(
        stock_id="2330",
        action=TradeAction.BUY,
        order_type=OrderType.LIMIT,
        quantity=1,
        limit_price=100,
    )

    order.submit()

    assert order.status == OrderStatus.SUBMITTED
    assert order.reason is None


def test_order_rejects_hold_submission() -> None:
    order = Order(
        stock_id="2330",
        action=TradeAction.HOLD,
        order_type=OrderType.LIMIT,
        quantity=1,
        limit_price=100,
    )

    with pytest.raises(ValueError, match="HOLD is not an executable order action"):
        order.validate_submission()


def test_order_fill_applies_limit_price_rules() -> None:
    order = Order(
        stock_id="2330",
        action=TradeAction.BUY,
        order_type=OrderType.LIMIT,
        quantity=1,
        limit_price=100,
    )

    with pytest.raises(ValueError, match="BUY fill price cannot exceed limit_price"):
        order.fill(101)

    order.fill(99)

    assert order.status == OrderStatus.FILLED
    assert order.average_filled_price == 99


def test_order_requires_reason_for_terminal_failures() -> None:
    order = Order(
        stock_id="2330",
        action=TradeAction.BUY,
        order_type=OrderType.LIMIT,
        quantity=1,
        limit_price=100,
    )

    with pytest.raises(ValueError, match="Failed order requires a reason"):
        order.fail(" ")


def test_position_add_recalculates_average_cost() -> None:
    position = Position(
        stock_id="2330",
        quantity=10,
        average_cost=100,
    )

    position.add(
        quantity=5,
        price=130,
    )

    assert position.quantity == 15
    assert position.average_cost == pytest.approx(110)


def test_position_reduce_keeps_active_position_positive() -> None:
    position = Position(
        stock_id="2330",
        quantity=10,
        average_cost=100,
    )

    position.reduce(4)

    assert position.quantity == 6
    assert position.remaining_after_sell(6) == 0


def test_position_rejects_oversell() -> None:
    position = Position(
        stock_id="2330",
        quantity=10,
        average_cost=100,
    )

    with pytest.raises(ValueError, match="Position quantity is insufficient"):
        position.remaining_after_sell(11)


def test_account_buy_updates_cash_and_position() -> None:
    position = Position(
        stock_id="2330",
        quantity=10,
        average_cost=100,
    )
    account = Account(
        cash=1000,
        positions=[position],
    )

    updated_position = account.buy(
        stock_id="2330",
        quantity=5,
        price=130,
        total_cost=650,
    )

    assert account.cash == 350
    assert updated_position.quantity == 15
    assert updated_position.average_cost == pytest.approx(110)
    assert account.position_for("2330") is position


def test_account_buy_creates_new_position() -> None:
    account = Account(cash=1000)

    position = account.buy(
        stock_id="2330",
        quantity=5,
        price=100,
        total_cost=500,
    )

    assert account.cash == 500
    assert account.position_for("2330") is position
    assert position.quantity == 5
    assert position.average_cost == 100


def test_account_sell_updates_cash_and_removes_closed_position() -> None:
    account = Account(
        cash=1000,
        positions=[
            Position(
                stock_id="2330",
                quantity=10,
                average_cost=100,
            )
        ]
    )

    remaining_quantity = account.sell(
        stock_id="2330",
        quantity=10,
        cash_delta=950,
    )

    assert remaining_quantity == 0
    assert account.cash == 1950
    assert account.position_for("2330") is None


def test_account_rejects_missing_sell_position() -> None:
    account = Account(cash=1000)

    with pytest.raises(ValueError, match="Position not found"):
        account.sell(
            stock_id="2330",
            quantity=1,
            cash_delta=100,
        )
