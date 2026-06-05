# backend/src/b_application/use_cases/collect/watchlist.py

from a_domain.model.market.stock import Stock
from a_domain.ports.analysis import IIndicatorProvider
from a_domain.ports.market import IPriceProvider, IStockProvider
from a_domain.ports.system import ILoggingProvider, IMarketClock
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.rules.scoring.technical import TechnicalScoreCalculator
from a_domain.types.enums import CandidateSource
from b_application.factories import TechnicalPolicyFactory
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


# TODO: Check the code here.
class Watchlist:
    """
    Use Case: Build nightly technical watchlist.

    This phase scans the full universe and stores technical candidates for intraday selection.
    """

    def __init__(
        self,
        stock_provider: IStockProvider,
        price_provider: IPriceProvider,
        indicator_provider: IIndicatorProvider,
        watchlist_repo: IWatchlistRepository,
        logger: ILoggingProvider,
        config: AppConfig,
        market_clock: IMarketClock,
    ):
        self._stock_provider = stock_provider
        self._price_provider = price_provider
        self._indicator = indicator_provider
        self._policy = TechnicalPolicyFactory().create(config.analysis.active_strategy, config.strategy)
        self._score = TechnicalScoreCalculator(
            base=config.scoring.base,
            pass_bonus=config.scoring.pass_bonus,
            hard_failure_penalty=config.scoring.hard_failure_penalty,
            max_hard_penalty=config.scoring.max_hard_penalty,
            soft_failure_penalty=config.scoring.soft_failure_penalty,
            max_soft_penalty=config.scoring.max_soft_penalty,
            rsi_sweet_spot_bonus=config.scoring.rsi_sweet_spot_bonus,
            rsi_sweet_spot_min=config.scoring.rsi_sweet_spot_min,
            rsi_sweet_spot_max=config.scoring.rsi_sweet_spot_max,
            macd_bullish_bonus=config.scoring.macd_bullish_bonus,
            ma_present_bonus=config.scoring.ma_present_bonus,
        )
        self._repo = watchlist_repo
        self._logger = logger
        self._config = config
        self._clock = market_clock

    async def execute(self, context: PipelineContext) -> None:
        stocks = await self._stock_provider.get_all()

        if not stocks:
            self._logger.warning("No stocks loaded for technical watchlist generation.")
            return

        self._logger.info(f"Generating technical watchlist from {len(stocks)} symbols.")

        start_date, end_date = self._clock.history_window(self._config.analysis.lookback_days)
        history_map = await self._price_provider.fetch_history(stocks, start_date, end_date)

        passed: list[Stock] = []

        for stock in stocks:
            history = history_map.get(stock.stock_id, [])

            if not history:
                continue

            stock.ohlcv = history
            stock.indicators = self._indicator.calculate_indicators(history)
            stock.source = CandidateSource.TECHNICAL_WATCHLIST
            stock.trigger_reason = "Nightly Technical Screen"

            self._policy.evaluate(stock)
            stock.technical_score = self._score.calculate(stock)

            if stock.is_eliminated:
                continue

            passed.append(stock)

        await self._repo.save_technical_watchlist(passed)

        context.technical_watchlist = passed
        context.stats.total_scanned = len(stocks)
        context.stats.passed_technical = len(passed)

        self._logger.info(f"Saved {len(passed)} stocks to Technical Watchlist.")
