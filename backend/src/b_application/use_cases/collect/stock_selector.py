# backend/src/b_application/use_cases/collect/stock_selector.py

from a_domain.model.market.stock import Stock
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import CandidateSource
from b_application.schemas.pipeline_context import PipelineContext


class StockSelector:
    """
    Use Case: Build the intraday candidate list.

    Intraday analysis should not care where a stock came from.
    This use case merges all candidate sources and deduplicates by stock_id.
    """

    def __init__(
        self,
        watchlist_repo: IWatchlistRepository,
        stock_provider: IStockProvider,
        logger: ILoggingProvider,
    ):
        self._watchlist_repo = watchlist_repo
        self._stock_provider = stock_provider
        self._logger = logger

    async def execute(self, context: PipelineContext) -> None:
        # Merges all candidate sources.
        # Held positions must be included even if they are not in today's technical or buzz lists.

        selected: dict[str, Stock] = {}
        # Deduplication map.
        # Key is stock_id, value is the Stock context used by downstream use cases.

        self._add_many(selected, context.held_candidates)

        technical_watchlist = context.technical_watchlist
        # Prefer current workflow state.
        # If empty, load persisted watchlist from repository.

        if not technical_watchlist:
            technical_watchlist = await self._watchlist_repo.get_technical_watchlist()

        self._add_many(selected, technical_watchlist)

        buzz_watchlist = context.buzz_watchlist

        if not buzz_watchlist:
            buzz_pairs = await self._watchlist_repo.get_buzz_watchlist()
            buzz_watchlist = []

            for stock, reason in buzz_pairs:
                stock.source = CandidateSource.SOCIAL_BUZZ
                stock.trigger_reason = reason
                buzz_watchlist.append(stock)

        self._add_many(selected, buzz_watchlist)

        for stock_id in context.manual_symbols:
            stock = await self._stock_provider.get_by_id(stock_id)

            if stock is None:
                self._logger.warning(f"Manual stock not found: {stock_id}")
                continue

            stock.source = CandidateSource.MANUAL_INPUT
            stock.trigger_reason = "User Manual Request"
            self._add_one(selected, stock)

        context.candidates = list(selected.values())

        self._logger.info(
            f"Selected {len(context.candidates)} candidates "
            f"(held={len(context.held_candidates)}, "
            f"technical={len(technical_watchlist)}, "
            f"buzz={len(buzz_watchlist)}, "
            f"manual={len(context.manual_symbols)})"
        )

    def _add_many(self, selected: dict[str, Stock], stocks: list[Stock]) -> None:
        """
        Adds many stocks into the deduplication map.

        This keeps the main execute flow readable while preserving one deduplication rule.
        """
        for stock in stocks:
            self._add_one(selected, stock)

    # TODO: remove helper
    def _add_one(self, selected: dict[str, Stock], stock: Stock) -> None:
        """
        Adds one stock without overwriting held-position context.

        If a stock is already held, HELD_POSITION should remain visible as the strongest application context.
        DecisionRule still uses positions_by_stock_id, but preserving held source reduces confusion during debugging.
        """
        existing = selected.get(stock.stock_id)

        if existing is not None and existing.source == CandidateSource.HELD_POSITION:
            return

        selected[stock.stock_id] = stock
