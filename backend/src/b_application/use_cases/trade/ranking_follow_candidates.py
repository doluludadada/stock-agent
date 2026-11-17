from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.rules.trading.follow import FollowWindowRule, RankingHoldings, RankingHoldingsRule
from a_domain.rules.trading.ranking import Ranking
from a_domain.types.enums import FollowRefusal, Workflow
from b_application.config.app_config import AppConfig


class RankingFollowCandidates:
    """
    Use Case: What a follow of the monthly ranking may take now, on the broker the Pipeline's run chose: the user's
    mock account, or SinoPac. It returns which of the ranking's stocks that account holds and lacks and which holdings
    the ranking left (RankingHoldingsRule), and why a follow may not start now, or None. A real broker whose login is
    not on its simulation server is refused first (SimulationOnlyRule), before its account is read, so no ranking
    follow starts on a production login; then the market's phase decides (FollowWindowRule). A follow's run, given as
    `stats`, asks it before its orders and again after them, and keeps how many stocks it still had to trade at each
    look, so the record says whether the follow finished the decision: the schedule follows a decision again until
    one did. The run also keeps the decision it took and the formula that made the ranking, as it was defined then, so
    its orders are never credited to a formula chosen later. A run refused for the login's server or the market's
    phase took nothing and keeps neither, and a ranking that decides nothing leaves the record as it was.
    """

    def __init__(self, broker: IExecutionProvider, market_clock: IMarketClock, config: AppConfig) -> None:
        self._broker = broker
        self._market_clock = market_clock
        self._simulation_rule = config.broker_access_rule().gate_rule.simulation_rule
        self._holdings_rule = RankingHoldingsRule()
        self._window_rule = FollowWindowRule(pricing=config.audience.order_pricing)

    async def execute(self, ranking: Ranking, stats: SystemStats | None = None) -> tuple[RankingHoldings, FollowRefusal | None]:
        if self._simulation_rule.apply(Workflow.RANKING_FOLLOW, self._broker.link()) is not None:
            return RankingHoldings(decided_on=ranking.decided_on), FollowRefusal.NOT_SIMULATION

        holdings = self._holdings_rule.apply(ranking, await self._broker.get_account())
        refusal = self._window_rule.apply(holdings.open, self._market_clock.trading_phase())
        window_closed = refusal is not None and refusal.lifts_later

        if stats is None or not ranking.decides:
            return holdings, refusal

        stats.ranking_open = len(holdings.open)

        if not window_closed:
            stats.ranking_formula, stats.ranking_decided_on = ranking.formula, ranking.decided_on

        return holdings, refusal
