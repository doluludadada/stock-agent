from a_domain.model.market.stock import Stock
from a_domain.rules.trading.decision import DecisionCandidatesRule
from b_application.schemas.pipeline_status import PipelineStatus


class DecisionCandidates:
    """
    Use Case: The stocks Intraday decides on once the technical filter has run (DecisionCandidatesRule): the run's
    survivors, then the held stocks among `technical_candidates` that failed the strategy.
    """

    def __init__(self) -> None:
        self._candidates_rule = DecisionCandidatesRule()

    def execute(self, technical_candidates: list[Stock], status: PipelineStatus) -> list[Stock]:
        return self._candidates_rule.apply(technical_candidates, status.survivors, status.account)
