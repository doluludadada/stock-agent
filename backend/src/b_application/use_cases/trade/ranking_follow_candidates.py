from collections.abc import Mapping

from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.rules.trading.follow import FollowAccount, FollowWindowRule, RankingHoldings, RankingHoldingsRule
from a_domain.rules.trading.ranking import Ranking
from a_domain.types.enums import ExecutionProvider, FollowRefusal
from a_domain.types.errors import FollowAccountChanged
from b_application.config.app_config import AppConfig


class RankingFollowCandidates:
    """
    Use Case: What a follow of the monthly ranking may take now on the user's follow account (`account`, as
    RankingFollowSchedule answered it): which of the ranking's stocks that account holds and lacks and which holdings
    the ranking left (RankingHoldingsRule), and why a follow may not start now, or None. An account the site does not
    offer the user now (`account.refusal`) is not read: the holdings are empty and the follow says nothing more. A
    follow's run, given as `stats`, must have started on that account, FollowAccountChanged otherwise, before anything
    is read, so no run reads one account and orders on another. Otherwise it reads the account's positions in one
    request (`accounts`, the user's), never an order, and the market's phase decides (FollowWindowRule). The run asks
    it before its orders and again after them, and keeps how many stocks it still had to trade at each look, so the
    record says whether the follow finished the decision: the schedule follows a decision again until one did. The run
    also keeps the decision it took and the formula that made the ranking, as it was defined then, so its orders are
    never credited to a formula chosen later. A run refused for the market's phase took nothing and keeps neither, and
    a ranking that decides nothing leaves the record as it was.
    """

    def __init__(
        self, accounts: Mapping[ExecutionProvider, IExecutionProvider], market_clock: IMarketClock, config: AppConfig
    ) -> None:
        self._accounts = accounts
        self._market_clock = market_clock
        self._holdings_rule = RankingHoldingsRule()
        self._window_rule = FollowWindowRule(pricing=config.audience.order_pricing)

    async def execute(
        self, account: FollowAccount, ranking: Ranking, stats: SystemStats | None = None
    ) -> tuple[RankingHoldings, FollowRefusal | None]:
        if stats is not None and stats.execution_provider != account.broker:
            raise FollowAccountChanged(
                f"This follow started on {stats.execution_provider.label}, and the follow account is {account.broker.label} now."
            )

        if account.refusal is not None:
            return RankingHoldings(decided_on=ranking.decided_on), None

        positions = await self._accounts[account.broker].open_positions()
        holdings = self._holdings_rule.apply(ranking, frozenset(position.stock_id for position in positions))
        refusal = self._window_rule.apply(holdings.open, self._market_clock.trading_phase())
        window_closed = refusal is not None and refusal.lifts_later

        if stats is None or not ranking.decides:
            return holdings, refusal

        stats.ranking_open = len(holdings.open)

        if not window_closed:
            stats.ranking_formula, stats.ranking_decided_on = ranking.formula, ranking.decided_on

        return holdings, refusal
