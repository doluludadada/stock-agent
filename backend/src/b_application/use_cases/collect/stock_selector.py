from a_domain.model.market.stock import Stock
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.rules.collect import CandidateSelectionRule
from a_domain.types.enums import CandidateSource
from b_application.schemas.pipeline_context import PipelineContext


class StockSelector:
    """
    Use Case: Build the intraday candidate list.

    This use case only loads candidate sources and delegates selection priority
    to CandidateSelectionRule.
    """

    def __init__(
        self,
        watchlist_repo: IWatchlistRepository,
        stock_provider: IStockProvider,
        logger: ILoggingProvider,
    ):
        self._watchlist_repo = watchlist_repo
        self._stock_provider = stock_provider
        self._candidate_selection_rule = CandidateSelectionRule()
        self._logger = logger

    async def execute(self, context: PipelineContext) -> None:
        technical_watchlist = context.technical_watchlist

        if not technical_watchlist:
            technical_watchlist = await self._watchlist_repo.get_technical_watchlist()

        buzz_watchlist = context.buzz_watchlist

        if not buzz_watchlist:
            buzz_pairs = await self._watchlist_repo.get_buzz_watchlist()
            buzz_watchlist = []

            for stock, reason in buzz_pairs:
                stock.source = CandidateSource.SOCIAL_BUZZ
                stock.trigger_reason = reason
                buzz_watchlist.append(stock)

        manual_stocks: list[Stock] = []

        for stock_id in context.manual_symbols:
            stock = await self._stock_provider.get_by_id(stock_id)

            if stock is None:
                self._logger.warning(f"Manual stock not found: {stock_id}")
                continue

            stock.source = CandidateSource.MANUAL_INPUT
            stock.trigger_reason = "User Manual Request"
            manual_stocks.append(stock)

        context.candidates = self._candidate_selection_rule.select(
            held=context.held_candidates,
            technical=technical_watchlist,
            buzz=buzz_watchlist,
            manual=manual_stocks,
            excluded_stock_ids=context.risk_blocked_stock_ids,
        )

        self._logger.info(
            f"Selected {len(context.candidates)} candidates "
            f"(held={len(context.held_candidates)}, "
            f"technical={len(technical_watchlist)}, "
            f"buzz={len(buzz_watchlist)}, "
            f"manual={len(context.manual_symbols)}, "
            f"risk_blocked={len(context.risk_blocked_stock_ids)})"
        )
