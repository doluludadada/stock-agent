from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class Signals:
    """Generates trading decisions and records them. Only recorded decisions reach the run's signals."""

    def __init__(self, journal: ITradingJournal, config: AppConfig, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._decision_rule = config.decision_rule()
        self._logger = logger

    async def execute(self, watchlist: StockWatchlist, status: PipelineStatus) -> None:
        self._logger.info(f"Generating signals for {len(watchlist.willing_stocks)} watchlist stocks.")

        generated_signals = [
            signal for stock in watchlist.willing_stocks if (signal := self.generate_signal(stock, status)) is not None
        ]

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

    def generate_signal(self, stock: Stock, status: PipelineStatus) -> TradeSignal | None:
        if stock.stock_id in status.risk_blocked_stock_ids:
            self._logger.warning(f"Signal skipped. Risk blocked: {stock.stock_id}")
            return None

        if stock.stock_id in status.stale_stock_ids:
            self._logger.warning(f"Signal skipped. Market data is stale: {stock.stock_id}")
            return None

        if stock.composite_score is None:
            self._logger.warning(f"Signal skipped. Composite score unavailable: {stock.stock_id}")
            return None

        try:
            return self._decision_rule.decide(
                stock=stock, account=status.account, position=status.account.position_for(stock.stock_id)
            )

        except Exception as error:
            message = f"Signal generation failed for {stock.stock_id}: {error}"
            self._logger.error(message)
            status.stats.add_error(message)
            return None
