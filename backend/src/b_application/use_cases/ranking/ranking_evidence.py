from dataclasses import replace
from datetime import date
from time import perf_counter

from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.trading.ranking import RankingHistory
from a_domain.rules.trading.ranking_backtest import RankingBacktest
from a_domain.types.values import FormulaId
from b_application.config.app_config import AppConfig


class RankingEvidence:
    """
    The evidence beside the choice of a formula: every formula of ranking.formulas replayed from `first` to `last` on
    the same history, at the same fee and tax, and again with ranking.evidence_min_traded_value as its liquidity floor,
    in the settings' order, with the name of the active one. One replay at a time, each kept by the matrix provider
    while the history stands, so the comparison never takes more than one core and a second look costs nothing. It
    reads no account and places no order. BacktestPeriodUnavailable for a period without a decision session.
    """

    def __init__(
        self, matrix_provider: IDailyBarMatrixProvider, stock_provider: IStockProvider, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        self._matrix_provider = matrix_provider
        self._stock_provider = stock_provider
        self._formulas = config.ranking.formulas
        self._active_formula = config.ranking.active_formula
        self._liquid_floor = config.ranking.evidence_min_traded_value
        self._replay_rule = config.ranking_backtest_rule
        self._logger = logger

    async def execute(
        self, history: RankingHistory, first: date, last: date
    ) -> tuple[FormulaId, list[tuple[RankingBacktest, RankingBacktest]]]:
        started = perf_counter()
        names = {stock.stock_id: stock.name for stock in await self._stock_provider.get_all()}
        evidence: list[tuple[RankingBacktest, RankingBacktest]] = []

        for formula in self._formulas:
            liquid = replace(formula, min_traded_value=self._liquid_floor)
            evidence.append(
                (
                    await self._matrix_provider.ranking_backtest(history, self._replay_rule(formula), names, first, last),
                    await self._matrix_provider.ranking_backtest(history, self._replay_rule(liquid), names, first, last),
                )
            )

        self._logger.info(
            f"Ranking evidence from {first} to {last}: {len(evidence)} formulas, each at its own floor and at "
            f"{self._liquid_floor:,.0f}, {perf_counter() - started:.1f}s"
        )

        return self._active_formula, evidence
