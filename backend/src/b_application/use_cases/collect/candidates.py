"""
Use Case: Select candidates from watchlists and manual input.

Entry point of the intraday pipeline.
"""
from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.ports.input.watchlist_repository import IWatchlistRepository
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.types.constants import REASON_MANUAL_REQ
from backend.src.a_domain.types.enums import CandidateSource


class Candidates:
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

    # TODO: Terrible writing way 
    def _to_pipeline_stock(self, stock: Stock, source: CandidateSource, reason: str) -> Stock:
        """Create a fresh Stock instance for the pipeline from an identity-only Stock."""
        return Stock(
            stock_id=stock.stock_id,
            market=stock.market,
            name=stock.name,
            industry=stock.industry,
            source=source,
            trigger_reason=reason,
        )

    async def execute(self, manual_symbols: list[str] | None = None) -> list[Stock]:
        candidates_map: dict[str, Stock] = {}

        # 1. Manual Input (highest priority)
        if manual_symbols:
            self._logger.info(f"Processing manual input: {manual_symbols}")
            stocks = await self._repo.get_stocks_by_ids(manual_symbols)
            for stock in stocks:
                candidates_map[stock.stock_id] = self._to_pipeline_stock(
                    stock, CandidateSource.MANUAL_INPUT, REASON_MANUAL_REQ
                )

        # 2. Buzz Watchlist (hot data)
        buzz_items = await self._repo.get_buzz_watchlist()
        for stock, reason in buzz_items:
            if stock.stock_id not in candidates_map:
                candidates_map[stock.stock_id] = self._to_pipeline_stock(
                    stock, CandidateSource.SOCIAL_BUZZ, reason
                )

        # 3. Technical Watchlist (cold data, skip if manual input provided)
        if not manual_symbols:
            daily_stocks = await self._repo.get_technical_watchlist()
            for stock in daily_stocks:
                if stock.stock_id not in candidates_map:
                    candidates_map[stock.stock_id] = self._to_pipeline_stock(
                        stock, CandidateSource.TECHNICAL_WATCHLIST, "Daily Screen"
                    )

        result = list(candidates_map.values())
        self._logger.info(f"Selected {len(result)} candidates")
        return result
