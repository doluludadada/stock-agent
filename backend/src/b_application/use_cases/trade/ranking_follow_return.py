from collections.abc import Mapping
from datetime import date

from a_domain.model.trading.account import Account
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import ISimulatedExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.follow import FollowReturn, RankingFollowReturnRule
from a_domain.rules.trading.ranking import RankingHistory
from a_domain.types.enums import Workflow
from b_application.config.app_config import AppConfig


class RankingFollowReturn:
    """
    Use Case: What the user's mock account made since it first followed the ranking, against the ranking's benchmark
    over the same sessions (RankingFollowReturnRule). The first follow is the first ranking follow's order that filled
    since the mock account opened, from the trading journal. None while the account never followed.
    """

    def __init__(
        self, journal: ITradingJournal, mock_broker: ISimulatedExecutionProvider, market_clock: IMarketClock, config: AppConfig
    ) -> None:
        self._journal = journal
        self._mock_broker = mock_broker
        self._market_clock = market_clock
        self._return_rule = RankingFollowReturnRule(benchmark_id=config.ranking.benchmark_id)

    async def execute(self, history: RankingHistory, account: Account, curve: Mapping[date, Account]) -> FollowReturn | None:
        if account.opening is None:
            return None

        filled_at = await self._journal.first_fill(Workflow.RANKING_FOLLOW, self._mock_broker.link().broker, account.opened_at)

        if filled_at is None:
            return None

        return self._return_rule.apply(self._market_clock.to_trading_date(filled_at), account.opening, curve, history)
