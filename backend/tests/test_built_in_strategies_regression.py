"""
The built-in strategies replaced HEAD's hand-written criteria classes (commit 1c256b7) with formulas. Their scores on
300 seeded random stocks were recorded from those classes in tests/fixtures/technical/criteria_scores.jsonl; the
formulas must reproduce every one: score, pass, how many hard and soft failures, and which bonuses were detected.
"""

import json
from pathlib import Path

from support.random_stocks import random_stocks
from support.settings import shipped_config

RECORDED = Path(__file__).parent / "fixtures" / "technical" / "criteria_scores.jsonl"


def test_built_in_strategies_score_every_stock_as_the_criteria_they_replaced() -> None:
    recorded = [json.loads(line) for line in RECORDED.read_text().splitlines()]
    strategies = {strategy.strategy_id: strategy for strategy in shipped_config().technical.built_in_strategies}
    scored = []

    for stock in random_stocks(300, 11):
        for strategy_id in sorted(strategies):
            report = strategies[strategy_id].apply(stock)
            scored.append(
                {
                    "stock": stock.stock_id,
                    "strategy": strategy_id,
                    "score": report.score,
                    "passed": report.passed,
                    "hard": len(report.hard_failures),
                    "soft": len(report.soft_failures),
                    "detected": [observation.endswith(": detected") for observation in report.observations],
                }
            )

    assert scored == recorded
    assert sum(row["detected"][1] for row in recorded) > 0, "the sample must contain Golden Cross events"
