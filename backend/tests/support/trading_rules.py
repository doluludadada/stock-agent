"""Trading rules built from explicit numbers, for tests that probe settings outside what appsetting.yaml allows."""

from datetime import date

from a_domain.rules.trading.cost import AffordableQuantityRule, TradingCostRule
from a_domain.rules.trading.decision import DecisionRule, RunDecisionsRule
from a_domain.rules.trading.entry import EntryRule
from a_domain.rules.trading.exit import ExitRule, StopLossRule
from a_domain.rules.trading.reason import AnalysisSummaryRule, EntryReasonRule, ExitReasonRule
from a_domain.rules.trading.sizing import BuyCostRule, SizingRule
from support.settings import shipped_config

COSTS = TradingCostRule(
    fee_rate=0.001425, tax_rate=0.003, etf_tax_rate=0.001, min_fee=20, bond_etf_tax_exempt_until=date(2026, 12, 31)
)
LIMIT_PRICE = shipped_config().market.limit_price_rule()
SUMMARY = AnalysisSummaryRule(item_limit=3)
ENTRY_REASON = EntryReasonRule(item_limit=3, summary_rule=SUMMARY)
EXIT_REASON = ExitReasonRule(item_limit=3, summary_rule=SUMMARY)


def sizing_rule(risk_per_trade_pct: float, stop_loss_pct: float = 0.10, lot_size: int = 1) -> SizingRule:
    return SizingRule(
        risk_per_trade_pct=risk_per_trade_pct,
        stop_loss_pct=stop_loss_pct,
        lot_size=lot_size,
        limit_price_rule=LIMIT_PRICE,
        affordable_quantity_rule=AffordableQuantityRule(cost_rule=COSTS),
    )


def entry_rule(buy_threshold: int, risk_per_trade_pct: float = 0.02) -> EntryRule:
    return EntryRule(buy_threshold=buy_threshold, sizing_rule=sizing_rule(risk_per_trade_pct), reason_rule=ENTRY_REASON)


def run_decisions_rule(risk_per_trade_pct: float, buy_threshold: int = 70, sell_threshold: int = 30) -> RunDecisionsRule:
    stop_loss_rule = StopLossRule(stop_loss_pct=0.10, reason_rule=EXIT_REASON)
    decision_rule = DecisionRule(
        entry_rule=entry_rule(buy_threshold, risk_per_trade_pct),
        exit_rule=ExitRule(sell_threshold=sell_threshold, stop_loss_rule=stop_loss_rule, reason_rule=EXIT_REASON),
    )

    return RunDecisionsRule(decision_rule=decision_rule, buy_cost_rule=BuyCostRule(limit_price_rule=LIMIT_PRICE, cost_rule=COSTS))
