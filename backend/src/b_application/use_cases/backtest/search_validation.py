from dataclasses import replace

from a_domain.ports.trading.candidate_backtester import ICandidateBacktester
from a_domain.rules.technical.search import FittestRule, SearchHistory, SearchTrial
from a_domain.types.enums import SearchSpan
from b_application.config.app_config import AppConfig


class SearchValidation:
    """
    Picks a search's winners on the validation span: the origin and the best on train (strategy_search.finalists) are
    backtested on validation, and the best there (strategy_search.winners) win. Returns the origin, then the winners,
    best first, each with its validation result.
    """

    def __init__(self, backtester: ICandidateBacktester, config: AppConfig) -> None:
        self._backtester = backtester
        self._fittest_rule = FittestRule(fitness_rule=config.strategy_search.fitness_rule())
        self._finalists, self._winners = config.strategy_search.finalists, config.strategy_search.winners

    async def execute(self, trials: list[SearchTrial], history: SearchHistory) -> list[SearchTrial]:
        checked = [trials[0], *self._fittest_rule.apply(trials, SearchSpan.TRAIN, self._finalists)]
        candidates = [trial.candidate for trial in checked]
        results = await self._backtester.backtest(history.bars, candidates, *history.spans[SearchSpan.VALIDATION])
        validated = [
            replace(trial, results={**trial.results, SearchSpan.VALIDATION: found})
            for trial, found in zip(checked, results, strict=True)
        ]

        return [validated[0], *self._fittest_rule.apply(validated[1:], SearchSpan.VALIDATION, self._winners)]
