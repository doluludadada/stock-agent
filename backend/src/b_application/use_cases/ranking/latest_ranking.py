from dataclasses import replace

from pydantic import PositiveInt

from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.rules.trading.ranking import Ranking, RankingHistory
from a_domain.types.errors import RankingUnavailable
from b_application.config.app_config import AppConfig


class LatestRanking:
    """
    The monthly ranking at the latest decision session the history holds (DecisionSessionsRule, MonthlyRankingRule),
    each stock with its name in the exchange listing. A history too short for a factor ranks nothing, and says how many
    stocks it had in its universe. It holds ranking.top stocks, or the `top` best scores when the caller names how
    many. RankingUnavailable when the history holds no decision session.
    """

    def __init__(self, stock_provider: IStockProvider, config: AppConfig) -> None:
        self._stock_provider = stock_provider
        self._decision_rule = config.decision_sessions_rule()
        self._ranking_rule = config.ranking.ranking_rule()

    async def execute(self, history: RankingHistory, top: PositiveInt | None = None) -> Ranking:
        decisions = self._decision_rule.apply(history.bars.sessions)

        if not decisions:
            raise RankingUnavailable(
                f"No ranking can be made yet: the daily history holds {history.bars.sessions[0]} to {history.bars.sessions[-1]}, "
                "and no decision session."
            )

        column, revenue_month = decisions[-1]
        names = {stock.stock_id: stock.name for stock in await self._stock_provider.get_all()}

        rule = self._ranking_rule if top is None else replace(self._ranking_rule, top=top)

        return rule.apply(history, column, revenue_month, names)
