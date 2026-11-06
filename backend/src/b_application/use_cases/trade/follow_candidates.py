from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import ISimulatedExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.follow import FollowWindowRule, OpenDecisionsRule
from a_domain.types.enums import FollowRefusal
from a_domain.types.ids import RunId
from b_application.config.app_config import AppConfig


class FollowCandidates:
    """
    Use Case: What a follow of one of the user's runs may take now. It returns the run (None when the journal holds no
    such run), its decisions still open to follow in the mock account as it stands (OpenDecisionsRule), every follow of
    them so far with its order, and why a follow may not start now (FollowWindowRule), or None. It reads the user's mock
    book, a simulator, never the broker the Pipeline orders on.
    """

    def __init__(
        self, journal: ITradingJournal, mock_broker: ISimulatedExecutionProvider, market_clock: IMarketClock, config: AppConfig
    ) -> None:
        self._journal = journal
        self._mock_broker = mock_broker
        self._market_clock = market_clock
        self._open_rule = OpenDecisionsRule()
        self._window_rule = FollowWindowRule(pricing=config.audience.order_pricing)

    async def execute(
        self, run_id: RunId
    ) -> tuple[SystemStats | None, list[TradeSignal], list[tuple[TradeSignal, Order]], FollowRefusal | None]:
        run = await self._journal.find_run(run_id)

        if run is None:
            return None, [], [], FollowRefusal.NOTHING_TO_FOLLOW

        decisions = await self._journal.signals_of(run_id)
        follows = await self._journal.follows_of(run_id)
        account = await self._mock_broker.get_account()
        open_decisions = self._open_rule.apply(run, decisions, follows, account)

        return run, open_decisions, follows, self._window_rule.apply(open_decisions, self._market_clock.trading_phase())
