from src.a_domain.ports.input.watchlist_repository import IWatchlistRepository
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.a_domain.types.constants import REASON_MANUAL_REQ
from src.a_domain.types.enums import CandidateSource
from src.b_application.schemas.stock_candidate import StockCandidate


class CandidateSelector:
    """
    Phase 3: Aggregates candidates from Repository Buckets.
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

        # 1. Manual Input
        if manual_symbols:
            self._logger.info(f"Processing manual input: {manual_symbols}")
            stocks = await self._repo.get_stocks_by_ids(manual_symbols)
            for stock in stocks:
                candidates_map[stock.stock_id] = StockCandidate(
                    stock=stock,
                    source=CandidateSource.MANUAL_INPUT,
                    trigger_note=REASON_MANUAL_REQ,  # Constant
                )

        # 2. Buzz Watchlist (Hot)
        buzz_items = await self._repo.get_buzz_watchlist()
        for stock, note in buzz_items:
            if stock.stock_id not in candidates_map:
                candidates_map[stock.stock_id] = StockCandidate(
                    stock=stock,
                    source=CandidateSource.SOCIAL_BUZZ,
                    trigger_note=note,  # Dynamic String from DB
                )

        # 3. Technical Watchlist (Cold)
        if not manual_symbols:
            daily_stocks = await self._repo.get_technical_watchlist()
            for stock in daily_stocks:
                if stock.stock_id not in candidates_map:
                    candidates_map[stock.stock_id] = StockCandidate(
                        stock=stock,
                        source=CandidateSource.TECHNICAL_WATCHLIST,
                        trigger_note="Daily Screen",  # Or use a Constant if generic
                    )

        result = list(candidates_map.values())
        self._logger.info(f"Selected {len(result)} candidates.")
        return result
