from dataclasses import replace

from a_domain.model.trading.backtest import SearchInputs
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.candidate_backtester import ICandidateBacktester
from a_domain.rules.technical.search import LuckSampleRule, SearchHistory, SearchTrial, StrategySearch
from a_domain.types.enums import MarketIndex, SearchSpan
from b_application.config.app_config import AppConfig


class SearchHoldout:
    """
    Reports a search's winners on the holdout, the one step that reads it: the origin, the winners and the luck sample
    (LuckSampleRule) backtested over it in one call. Returns the search, with the TAIEX over its spans.
    """

    def __init__(
        self, backtester: ICandidateBacktester, ohlcv_provider: IOhlcvProvider, market_clock: IMarketClock, config: AppConfig
    ) -> None:
        self._backtester = backtester
        self._ohlcv_provider = ohlcv_provider
        self._market_clock = market_clock
        self._luck_rule = LuckSampleRule(fitness_rule=config.strategy_search.fitness_rule())
        self._luck_sample, self._finalists = config.strategy_search.luck_sample, config.strategy_search.finalists
        self._breeding_rule, self._split_rule = config.strategy_search.breeding_rule(), config.strategy_search.split_rule()

    async def execute(
        self, inputs: SearchInputs, history: SearchHistory, trials: list[SearchTrial], validated: list[SearchTrial]
    ) -> StrategySearch:
        spans, close = history.spans, self._market_clock.session_close
        backtested = [*validated, *self._luck_rule.apply(trials, self._luck_sample, inputs.random_seed)]
        results = await self._backtester.backtest(history.bars, [trial.candidate for trial in backtested], *spans[SearchSpan.HOLDOUT])
        reported = [
            replace(trial, results={**trial.results, SearchSpan.HOLDOUT: found})
            for trial, found in zip(validated, results, strict=False)
        ]
        whole = close(spans[SearchSpan.TRAIN][0]), close(spans[SearchSpan.HOLDOUT][1])

        return StrategySearch(
            inputs=inputs,
            started_at=history.started_at,
            finished_at=self._market_clock.now(),
            finalists=self._finalists,
            breeding=self._breeding_rule,
            split=self._split_rule,
            spans=spans,
            tried=len(trials),
            origin=reported[0],
            winners=reported[1:],
            luck_returns=[found.return_pct for found in results[len(validated) :]],
            benchmark=await self._ohlcv_provider.fetch_index_history(MarketIndex.TAIEX, *whole),
        )
