"""
Use Case: Select candidates from watchlists and manual input.

Entry point of the intraday pipeline.
"""
from backend.src.a_domain.model.analysis.stock_candidate import StockCandidate
from backend.src.a_domain.ports.input.watchlist_repository import IWatchlistRepository
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.types.constants import REASON_MANUAL_REQ
from backend.src.a_domain.types.enums import CandidateSource


class SelectCandidates:
    """
    Aggregates candidates from multiple sources.

    Priority (for deduplication):
    1. Manual Input (highest)
    2. Social Buzz
    3. Technical Watchlist (lowest)
    """

    def __init__(
        self,
        watchlist_repo: IWatchlistRepository,
        logger: ILoggingProvider,
    ):
        self._repo = watchlist_repo
        self._logger = logger

    async def execute(self, manual_symbols: list[str] | None = None) -> list[StockCandidate]:
        candidates_map: dict[str, StockCandidate] = {}

        # 1. Manual Input (highest priority)
        if manual_symbols:
            self._logger.info(f"Processing manual input: {manual_symbols}")
            stocks = await self._repo.get_stocks_by_ids(manual_symbols)
            for stock in stocks:
                candidates_map[stock.stock_id] = StockCandidate(
                    stock=stock,
                    source=CandidateSource.MANUAL_INPUT,
                    trigger_reason=REASON_MANUAL_REQ,
                )

        # 2. Buzz Watchlist (hot data)
        buzz_items = await self._repo.get_buzz_watchlist()
        for stock, reason in buzz_items:
            if stock.stock_id not in candidates_map:
                candidates_map[stock.stock_id] = StockCandidate(
                    stock=stock,
                    source=CandidateSource.SOCIAL_BUZZ,
                    trigger_reason=reason,
                )

        # 3. Technical Watchlist (cold data, skip if manual input provided)
        if not manual_symbols:
            daily_stocks = await self._repo.get_technical_watchlist()
            for stock in daily_stocks:
                if stock.stock_id not in candidates_map:
                    candidates_map[stock.stock_id] = StockCandidate(
                        stock=stock,
                        source=CandidateSource.TECHNICAL_WATCHLIST,
                        trigger_reason="Daily Screen",
                    )

        result = list(candidates_map.values())
        self._logger.info(f"Selected {len(result)} candidates")
        return result
