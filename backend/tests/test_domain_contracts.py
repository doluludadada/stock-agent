import pytest
from icontract.errors import ViolationError

from a_domain.model.indicators.technical_indicators import MovingAverages
from a_domain.model.trading.account import Account
from a_domain.rules.scoring import CompositeScoreRule
from a_domain.rules.technical.criteria.trend import MaAlignmentCriterion, PriceAboveMaCriterion
from a_domain.rules.trading import EntryRule, ExitRule, SizingRule


def test_moving_averages_require_positive_periods() -> None:
    with pytest.raises(ViolationError):
        MovingAverages(price_ma={0: 100.0})

    with pytest.raises(ViolationError):
        MovingAverages(price_ma={20: 0})


def test_trading_rules_reject_invalid_config() -> None:
    rule = SizingRule(position_pct=0, lot_size=1)
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
    sizing_rule = SizingRule(position_pct=0.02, lot_size=1)

    with pytest.raises(ViolationError):
        EntryRule(buy_threshold=101, sizing_rule=sizing_rule)


def test_sizing_rule_rejects_invalid_price() -> None:
    sizing_rule = SizingRule(position_pct=0.02, lot_size=1)

    with pytest.raises(ViolationError):
        sizing_rule.calculate(account=Account(cash=1000), price=0)


def test_composite_rule_rejects_zero_total_weight() -> None:
    with pytest.raises(ViolationError):
        CompositeScoreRule(technical_weight=0, sentiment_weight=0)
