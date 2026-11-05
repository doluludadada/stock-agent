from collections.abc import Sequence

from a_domain.model.valuation.valuation import StockValuation, ValuationReport
from a_domain.rules.valuation.valuation import AppraisalRule
from a_domain.types.values import PositiveFiniteFloat
from b_application.config.app_config import AppConfig


class ValuationAppraiser:
    """Use Case: values the chosen stocks at the user's target P/E, in the order chosen."""

    def __init__(self, config: AppConfig) -> None:
        self._appraisal_rule = AppraisalRule(scenario_spread=config.valuation.scenario_spread)

    def execute(self, valuations: Sequence[StockValuation], target_pe: PositiveFiniteFloat | None) -> list[ValuationReport]:
        return [self._appraisal_rule.apply(valuation, target_pe) for valuation in valuations]
