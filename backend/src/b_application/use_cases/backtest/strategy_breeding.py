from random import Random
from time import perf_counter

from a_domain.model.trading.backtest import SearchInputs
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.candidate_backtester import ICandidateBacktester
from a_domain.rules.technical.search import FittestRule, SearchHistory, SearchTrial, StrategyCandidate
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.types.enums import SearchSpan
from b_application.config.app_config import AppConfig


class StrategyBreeding:
    """
    Breeds candidates on the train span: the origin, the strategy at the inputs' two scores, then the inputs'
    generations of `population` children of the fittest so far (BreedingRule), each backtested on train alone. The same
    inputs breed the same candidates. Returns every candidate tried, once each, the origin first.
    """

    def __init__(self, backtester: ICandidateBacktester, config: AppConfig, logger: ILoggingProvider) -> None:
        self._backtester = backtester
        self._breeding_rule = config.strategy_search.breeding_rule()
        self._fitness_rule = config.strategy_search.fitness_rule()
        self._fittest_rule = FittestRule(fitness_rule=self._fitness_rule)
        self._logger = logger

    async def execute(self, strategy: TechnicalStrategy, inputs: SearchInputs, history: SearchHistory) -> list[SearchTrial]:
        started, seeds, population = perf_counter(), Random(inputs.random_seed), inputs.population
        bars, train = history.bars, history.spans[SearchSpan.TRAIN]
        origin = StrategyCandidate(strategy=strategy, buy_score=inputs.buy_score, sell_score=inputs.sell_score)
        trials = [
            SearchTrial(candidate=origin, results={SearchSpan.TRAIN: (await self._backtester.backtest(bars, [origin], *train))[0]})
        ]
        survivors, tried = trials, {origin.key}

        for generation in range(1, inputs.generations + 1):
            children = self._breeding_rule.apply(survivors, tried, inputs.level, strategy, population, seeds.getrandbits(64))
            results = await self._backtester.backtest(bars, children, *train)
            born = [
                SearchTrial(candidate=child, results={SearchSpan.TRAIN: found}) for child, found in zip(children, results, strict=True)
            ]
            trials, tried = [*trials, *born], tried | {child.key for child in children}
            survivors = self._fittest_rule.apply([*survivors, *born], SearchSpan.TRAIN, population)
            minutes, best = (perf_counter() - started) / 60, self._fitness_rule.apply(survivors[0].results[SearchSpan.TRAIN])
            self._logger.info(
                f"Generation {generation}/{inputs.generations}: {len(trials)} tried in {minutes:.1f} min, "
                f"{len(trials) / minutes:.0f} per minute; best train fitness {best:.4f}"
            )

        return trials
