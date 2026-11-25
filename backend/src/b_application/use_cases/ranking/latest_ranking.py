from dataclasses import replace

from pydantic import PositiveInt

from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.rules.trading.ranking import Ranking, RankingHistory, latest_decision
from a_domain.types.values import FormulaId
from b_application.config.app_config import AppConfig


class LatestRanking:
    """
    The monthly ranking at the latest decision session the history holds (DecisionSessionsRule, MonthlyRankingRule),
    each stock with its name in the exchange listing. A history too short for a factor ranks nothing, and says how many
    stocks it had in its universe. The formula is the one named, the active one when none is. It holds the formula's
    `top` stocks, or the `top` best scores when the caller names how many, and none while the formula holds cash.
    RankingUnavailable when the history holds no decision session, UnknownRankingFormula for a name the settings lack.
    """

    def __init__(self, stock_provider: IStockProvider, config: AppConfig) -> None:
        self._stock_provider = stock_provider
        self._decision_rule = config.decision_sessions_rule()
        self._ranking_rule = config.ranking.ranking_rule

    async def execute(self, history: RankingHistory, top: PositiveInt | None = None, formula_name: FormulaId | None = None) -> Ranking:
        ranking_rule = self._ranking_rule(formula_name)
        column, revenue_month = latest_decision(self._decision_rule, history.bars.sessions)
        names = {stock.stock_id: stock.name for stock in await self._stock_provider.get_all()}

        rule = ranking_rule if top is None else replace(ranking_rule, formula=replace(ranking_rule.formula, top=top))

        return rule.apply(history, column, revenue_month, names)
