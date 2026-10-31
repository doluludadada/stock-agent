from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.exit import BlockedStockRule, StopLossQuoteRule
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class AccountRiskCheck:
    """
    Use Case: Fast account-level risk pre-check.

    This runs after AccountLoader and realtime market-data refresh, and the workflow sends the
    stop-loss SELLs it records right away, while their quotes are fresh.

    It only checks emergency stop-loss, on held stocks whose quote StopLossQuoteRule accepts.
    It does not fetch market data or run score-based trading decisions.
    """

    def __init__(self, journal: ITradingJournal, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._market_clock = market_clock
        self._quote_rule = StopLossQuoteRule(blocked_rule=BlockedStockRule())
        self._stop_loss_rule = config.stop_loss_rule()
        self._logger = logger

    async def execute(self, status: PipelineStatus) -> None:
        if not status.held_stocks:
            self._logger.info("Account risk check skipped. No held positions.")
            return

        for stock in status.held_stocks:
            position = status.account.position_for(stock.stock_id)
            skip = self._quote_rule.apply(stock, status.risk_blocked_stock_ids, status.stale_stock_ids)

            if skip is not None:
                self._logger.warning(f"Risk check skipped. {skip}: {stock.stock_id}")
                continue

            signal = None if position is None else self._stop_loss_rule.apply(stock, position, now=self._market_clock.now())
            if signal is None:
                continue

            status.risk_blocked_stock_ids.add(signal.stock_id)
            try:
                await self._journal.save_signals(status.stats.run_id, [signal])
            except Exception as error:
                message = f"Stop-loss signal persistence failed, so it is not acted on: {signal.stock_id}, error={error}"
                self._logger.error(status.stats.add_error(message))
                continue
            status.signals.append(signal)
            status.stats.signals_generated += 1
            self._logger.warning(
                f"Emergency stop-loss signal generated: {signal.stock_id}, qty={signal.quantity}, "
                f"price={signal.price_at_signal}, stop_loss={signal.stop_loss_price}"
            )
