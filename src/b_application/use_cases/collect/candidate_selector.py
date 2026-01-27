
from src.a_domain.model.market.stock import Stock
from src.a_domain.ports.input.social_media_provider import ISocialMediaProvider
from src.a_domain.ports.input.watchlist_repository import IWatchlistRepository
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.a_domain.types.enums import CandidateSource
from src.b_application.schemas.stock_candidate import StockCandidate


class CandidateSelector:
    """
    Use Case: Selects targets for analysis from Manual, Buzz, and Watchlist sources.
    Priority: Manual > Buzz > Watchlist.
    """

    def __init__(
        self,
        watchlist_repo: IWatchlistRepository,
        social_provider: ISocialMediaProvider,
        logger: ILoggingProvider,
    ):
        self._watchlist_repo = watchlist_repo
        self._social_provider = social_provider
        self._logger = logger

    async def execute(self, manual_symbols: list[str] | None = None) -> list[StockCandidate]:
        # Use a dict to handle duplicates (Key: stock_id)
        candidates_map: dict[str, StockCandidate] = {}

        # -----------------------------------------------------------
        # 1. Manual Input (Highest Priority)
        # -----------------------------------------------------------
        if manual_symbols:
            self._logger.info(f"Processing manual input: {manual_symbols}")
            try:
                # Resolve Stock entities from local DB (Cold Data)
                stocks = await self._watchlist_repo.get_stocks_by_ids(manual_symbols)
                for stock in stocks:
                    candidates_map[stock.stock_id] = StockCandidate(
                        stock=stock, source=CandidateSource.MANUAL_INPUT, trigger_reason="User Manual Request"
                    )
            except Exception as e:
                self._logger.error(f"Failed to process manual inputs: {e}")

        # -----------------------------------------------------------
        # 2. Social Buzz (Medium Priority - Dynamic)
        # -----------------------------------------------------------
        self._logger.debug("Fetching trending stocks from Buzz Monitor...")
        try:
            # buzz_data is list of (stock_id, reason)
            buzz_data = await self._social_provider.get_trending_stocks(limit=10)

            # We need Stock entities. Batch fetch them.
            buzz_ids = [b[0] for b in buzz_data]
            if buzz_ids:
                buzz_stocks = await self._watchlist_repo.get_stocks_by_ids(buzz_ids)
                # Create a lookup for reason
                reason_map = {b[0]: b[1] for b in buzz_data}

                for stock in buzz_stocks:
                    if stock.stock_id in candidates_map:
                        # If already exists (e.g., Manual), just append reason
                        candidates_map[stock.stock_id].trigger_reason += f" | Buzz: {reason_map[stock.stock_id]}"
                    else:
                        candidates_map[stock.stock_id] = StockCandidate(
                            stock=stock,
                            source=CandidateSource.SOCIAL_BUZZ,
                            trigger_reason=reason_map.get(stock.stock_id, "Trending"),
                        )
        except Exception as e:
            self._logger.error(f"Failed to fetch buzz candidates: {e}")

        # -----------------------------------------------------------
        # 3. Technical Watchlist (Base Priority - Static)
        # -----------------------------------------------------------
        if not manual_symbols:
            self._logger.debug("Fetching technical watchlist from DB...")
            try:
                watchlist_stocks = await self._watchlist_repo.get_daily_candidates()
                for stock in watchlist_stocks:
                    if stock.stock_id not in candidates_map:
                        candidates_map[stock.stock_id] = StockCandidate(
                            stock=stock,
                            source=CandidateSource.TECHNICAL_WATCHLIST,
                            trigger_reason="Daily Technical Screen",
                        )
            except Exception as e:
                self._logger.error(f"Failed to fetch watchlist: {e}")

        result_list = list(candidates_map.values())
        self._logger.success(f"Candidate Selection Complete. Total: {len(result_list)}")
        return result_list
