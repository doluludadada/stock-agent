from collections.abc import Collection

from a_domain.rules.trading.ranking import RankingHistory, latest_decision
from a_domain.rules.trading.ranking_standing import RankingStanding, RankingStandingRule
from b_application.config.app_config import AppConfig


class StockRankingStanding:
    """
    Where each of `stock_ids` stands in the monthly ranking at the latest decision session the history holds
    (DecisionSessionsRule, RankingStandingRule, which ranks the market once for all of them): its place, its score from
    0 to 100 and its formula's factors, or why the ranking leaves it out. It is the ranking LatestRanking answers, with no cut
    at the active formula's top. RankingUnavailable when a stock is asked for and the history holds no decision session.
    """

    def __init__(self, config: AppConfig) -> None:
        self._decision_rule = config.decision_sessions_rule()
        self._standing_rule = RankingStandingRule(ranking_rule=config.ranking.ranking_rule())

    async def execute(self, history: RankingHistory, stock_ids: Collection[str]) -> dict[str, RankingStanding]:
        if not stock_ids:
            return {}

        column, revenue_month = latest_decision(self._decision_rule, history.bars.sessions)

        return self._standing_rule.apply(history, column, revenue_month, stock_ids)
