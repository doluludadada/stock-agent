from datetime import timedelta

from a_domain.ports.ai.stock_brief_repository import IStockBriefRepository
from a_domain.ports.ai.system_writing_log import ISystemWritingLog, SystemWriting
from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.market.price_provider import IPriceHistoryProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.users_stocks import IUsersStocks
from a_domain.rules.trading.ranking import latest_decision
from a_domain.types.errors import RankingUnavailable
from b_application.config.app_config import AppConfig


class SystemWritingStocks:
    """
    The stocks the site still writes for by itself now: once the daily bars of a new session are held, a round begins
    for the monthly ranking's top stocks at its latest decision session (the active formula's `top`), and, where
    stock_page.system_writing.users_stocks is on, the stocks users hold or watch after them. A stock of the round is
    done once it has a written brief of the day the round began or a later one, since its profile, its annual report
    and its card come before its brief; it answers the others, in the round's order. So a round that a restart, a
    spent budget or a failure stopped goes on where it stopped, and a round that is done answers nothing until the
    next session.

    It decides cheaply: the span of sessions the price source holds, the round the log keeps of the last one, and one
    look per stock of the round at its newest written brief. Only the first look of a session ranks the market, from
    the history the stock pages' rankings share (IDailyBarMatrixProvider), which is read from the database only when
    it changed. No round begins while no session is held, or while the history gives no ranking and no user's stock is
    taken. It fetches nothing and asks no AI.
    """

    def __init__(
        self,
        ohlcv_provider: IPriceHistoryProvider,
        matrix_provider: IDailyBarMatrixProvider,
        log: ISystemWritingLog,
        briefs: IStockBriefRepository,
        users_stocks: IUsersStocks,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._ohlcv_provider = ohlcv_provider
        self._matrix_provider = matrix_provider
        self._log = log
        self._briefs = briefs
        self._users_stocks = users_stocks
        self._market_clock = market_clock
        self._logger = logger
        self._users_stocks_too = config.stock_page.system_writing.users_stocks
        self._decision_rule = config.decision_sessions_rule()
        self._ranking_rule = config.ranking.ranking_rule()

    async def execute(self) -> list[str]:
        held = await self._ohlcv_provider.held_span()

        if held is None:
            return []

        today = self._market_clock.today()
        writing = await self._log.find(held[1])

        if writing is None:
            history = await self._matrix_provider.load_ranking_history()

            try:
                decision = latest_decision(self._decision_rule, history.bars.sessions) if history is not None else None
            except RankingUnavailable:
                decision = None

            ranked = self._ranking_rule.apply(history, *decision, {}).stocks if history is not None and decision else []
            followed = sorted(await self._users_stocks.held_or_watched()) if self._users_stocks_too else []
            stock_ids = list(dict.fromkeys([*(stock.stock_id for stock in ranked), *followed]))

            if not stock_ids:
                return []

            writing = await self._log.begin(SystemWriting(session=held[1], started_on=today, stock_ids=stock_ids))
            self._logger.info(f"System writing: a round of {len(writing.stock_ids)} stocks began for the session {held[1]}.")

        left = []

        for stock_id in writing.stock_ids:
            written = await self._briefs.latest_written(stock_id, today + timedelta(days=1))

            if written is None or written.day < writing.started_on:
                left.append(stock_id)

        return left
