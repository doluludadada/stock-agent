from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import CandidateSource, SignalReason
from b_application.schemas.pipeline_context import PipelineContext


class StockSelector:
    """
    Use Case: Select stocks from watchlists and manual input.
    Entry point of the intraday pipeline.
    """

    def __init__(self, watchlist_repo: IWatchlistRepository, logger: ILoggingProvider):
        self._repo = watchlist_repo
        self._logger = logger

    async def execute(self, ctx: PipelineContext) -> None:
        stock_map = {}

        # 1. Manual Input
        if ctx.manual_symbols:
            self._logger.info(f"Processing manual input: {ctx.manual_symbols}")
            stocks = await self._repo.get_stocks_by_ids(ctx.manual_symbols)
            for stock in stocks:
                stock.source = CandidateSource.MANUAL_INPUT
                stock.trigger_reason = SignalReason.MANUAL_REQ
                stock_map[stock.stock_id] = stock

        # 2. Buzz Watchlist
        buzz_items = await self._repo.get_buzz_watchlist()
        for stock, reason in buzz_items:
            if stock.stock_id not in stock_map:
                stock.source = CandidateSource.SOCIAL_BUZZ
                stock.trigger_reason = reason
                stock_map[stock.stock_id] = stock

        # 3. Technical Watchlist (skip if manual input provided)
        if not ctx.manual_symbols:
            daily_stocks = await self._repo.get_technical_watchlist()
            for stock in daily_stocks:
                if stock.stock_id not in stock_map:
                    stock.source = CandidateSource.TECHNICAL_WATCHLIST
                    stock.trigger_reason = SignalReason.NIGHTLY_SCREEN
                    stock_map[stock.stock_id] = stock

        ctx.candidates = list(stock_map.values())
        ctx.stats.total_scanned += len(ctx.candidates)
        self._logger.info(f"Selected {len(ctx.candidates)} stocks")
