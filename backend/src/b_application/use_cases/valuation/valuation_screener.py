from a_domain.model.valuation.scan import MarketValuation, ScanCriteria, ValuationScan
from a_domain.rules.valuation.scan import ValuationStepRule
from a_domain.rules.valuation.valuation import AppraisalRule
from b_application.config.app_config import AppConfig


class ValuationScreener:
    """Use Case: the undervalued scan's valuation step over the whole market, at the user's criteria."""

    def __init__(self, config: AppConfig) -> None:
        valuation = config.valuation
        self._valuation_step_rule = ValuationStepRule(
            appraisal_rule=AppraisalRule(scenario_spread=valuation.scenario_spread), max_explanations=valuation.max_scan_explanations
        )

    def execute(self, market: MarketValuation, criteria: ScanCriteria) -> ValuationScan:
        return self._valuation_step_rule.apply(market, criteria)
