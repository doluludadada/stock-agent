from a_domain.model.trading.stock_watchlist import StockWatchlist
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.decision import DecisionSkipRule
from a_domain.rules.trading.exit import BlockedStockRule
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class Signals:
    """
    Generates one run's trading decisions with RunDecisionsRule, every BUY sized on the run's equity, and records them.
    A stock DecisionSkipRule skips gets no decision. Only recorded decisions reach the run's signals, in decision order:
    best composite score first.
    """

    def __init__(self, journal: ITradingJournal, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._market_clock = market_clock
        self._skip_rule = DecisionSkipRule(blocked_rule=BlockedStockRule())
        self._decisions_rule = config.run_decisions_rule()
        self._logger = logger

    async def execute(self, watchlist: StockWatchlist, status: PipelineStatus) -> None:
        self._logger.info(f"Generating signals for {len(watchlist.willing_stocks)} watchlist stocks.")
        sold, stale = status.risk_blocked_stock_ids, status.stale_stock_ids
        skips = {stock.stock_id: skip for stock in watchlist.willing_stocks if (skip := self._skip_rule.apply(stock, sold, stale))}
        candidates = [stock for stock in watchlist.willing_stocks if stock.stock_id not in skips]

        for stock_id, skip in skips.items():
            self._logger.warning(f"Signal skipped. {skip}: {stock_id}")

        try:
            signals = self._decisions_rule.apply(candidates, status.account, status.require_equity(), now=self._market_clock.now())
        except Exception as error:
            message = f"Signal generation failed, so this run decides on none of {len(candidates)} stocks: {error}"
            self._logger.error(status.stats.add_error(message))
            return

        if not signals:
            self._logger.info("No new trading signals were generated.")
            return

        try:
            await self._journal.save_signals(status.stats.run_id, signals)
        except Exception as error:
            message = f"Signal persistence failed, so none of these {len(signals)} decisions is acted on: {error}"
            self._logger.error(status.stats.add_error(message))
            return

        status.signals.extend(signals)
        status.stats.signals_generated += len(signals)
        self._logger.info(f"Signals persisted: total={len(signals)}")
