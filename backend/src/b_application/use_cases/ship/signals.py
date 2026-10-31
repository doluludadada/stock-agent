from a_domain.model.market.stock import Stock
from a_domain.model.trading.stock_watchlist import StockWatchlist
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.trading_journal import ITradingJournal
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class Signals:
    """
    Generates one run's trading decisions with DecisionRule.decide_run and records them. Only recorded
    decisions reach the run's signals, in decision order: best composite score first.
    """

    def __init__(self, journal: ITradingJournal, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._market_clock = market_clock
        self._decision_rule = config.decision_rule()
        self._logger = logger

    async def execute(self, watchlist: StockWatchlist, status: PipelineStatus) -> None:
        self._logger.info(f"Generating signals for {len(watchlist.willing_stocks)} watchlist stocks.")

        candidates = [stock for stock in watchlist.willing_stocks if self.is_decidable(stock, status)]

        try:
            generated_signals = self._decision_rule.decide_run(candidates, status.account, now=self._market_clock.now())

        except Exception as error:
            message = f"Signal generation failed, so this run decides on none of {len(candidates)} stocks: {error}"
            self._logger.error(message)
            status.stats.add_error(message)
            return

        if not generated_signals:
            self._logger.info("No new trading signals were generated.")
            return

        try:
            await self._journal.save_signals(status.stats.run_id, generated_signals)

        except Exception as error:
            message = f"Signal persistence failed, so none of these {len(generated_signals)} decisions is acted on: {error}"
            self._logger.error(message)
            status.stats.add_error(message)
            return

        status.signals.extend(generated_signals)
        status.stats.signals_generated += len(generated_signals)
        self._logger.info(f"Signals persisted: total={len(generated_signals)}")

    def is_decidable(self, stock: Stock, status: PipelineStatus) -> bool:
        if stock.stock_id in status.risk_blocked_stock_ids:
            self._logger.warning(f"Signal skipped. Risk blocked: {stock.stock_id}")
            return False

        if stock.stock_id in status.stale_stock_ids:
            self._logger.warning(f"Signal skipped. Market data is stale: {stock.stock_id}")
            return False

        if stock.composite_score is None:
            self._logger.warning(f"Signal skipped. Composite score unavailable: {stock.stock_id}")
            return False

        if stock.current_price is None:
            self._logger.warning(f"Signal skipped. No price: {stock.stock_id}")
            return False

        return True
