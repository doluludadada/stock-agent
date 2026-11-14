from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import ISimulatedExecutionProvider
from a_domain.rules.trading.follow import FollowWindowRule, RankingHoldings, RankingHoldingsRule
from a_domain.rules.trading.ranking import Ranking
from a_domain.types.enums import FollowRefusal
from b_application.config.app_config import AppConfig


class RankingFollowCandidates:
    """
    Use Case: What a follow of the monthly ranking may take now. It returns which of the ranking's stocks the user's
    mock account holds and lacks and which holdings the ranking left (RankingHoldingsRule), and why a follow may not
    start now (FollowWindowRule), or None. It reads the user's mock book, a simulator, never the broker the Pipeline
    orders on.
    """

    def __init__(self, mock_broker: ISimulatedExecutionProvider, market_clock: IMarketClock, config: AppConfig) -> None:
        self._mock_broker = mock_broker
        self._market_clock = market_clock
        self._holdings_rule = RankingHoldingsRule()
        self._window_rule = FollowWindowRule(pricing=config.audience.order_pricing)

    async def execute(self, ranking: Ranking) -> tuple[RankingHoldings, FollowRefusal | None]:
        holdings = self._holdings_rule.apply(ranking, await self._mock_broker.get_account())

        return holdings, self._window_rule.apply(holdings.open, self._market_clock.trading_phase())
