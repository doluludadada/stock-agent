from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import TradeAction
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class AccountRiskCheck:
    """
    Use Case: Fast account-level risk pre-check.

    This runs after AccountLoader and realtime market-data refresh, and the workflow sends the
    stop-loss SELLs it records right away, while their quotes are fresh.

    It only checks emergency stop-loss.
    It does not fetch market data or run score-based trading decisions.
    """

    def __init__(self, journal: ITradingJournal, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._market_clock = market_clock
        self._exit_rule = config.decision_rule().exit_rule
        self._logger = logger

    async def execute(self, status: PipelineStatus) -> None:
        if not status.held_stocks:
            self._logger.info("Account risk check skipped. No held positions.")
            return

        for stock in status.held_stocks:
            if not self.has_executable_market_data(stock, status):
                continue

            position = status.account.position_for(stock.stock_id)

            if position is None:
                continue

            signal = self._exit_rule.decide_stop_loss_only(stock=stock, position=position, now=self._market_clock.now())

            if signal.action == TradeAction.SELL:
                await self.record_stop_loss(signal, status)

    def has_executable_market_data(self, stock: Stock, status: PipelineStatus) -> bool:
        if stock.stock_id in status.stale_stock_ids:
            self._logger.warning(f"Risk check skipped. Market data is stale: {stock.stock_id}")
            return False

        if stock.realtime_bar is None:
            self._logger.warning(f"Risk check skipped. Realtime bar unavailable: {stock.stock_id}")
            return False

        return True

    async def record_stop_loss(self, signal: TradeSignal, status: PipelineStatus) -> None:
        status.risk_blocked_stock_ids.add(signal.stock_id)

        try:
            await self._journal.save_signals(status.stats.run_id, [signal])

        except Exception as error:
            message = f"Stop-loss signal persistence failed, so it is not acted on: {signal.stock_id}, error={error}"
            self._logger.error(message)
            status.stats.add_error(message)
            return

        status.signals.append(signal)
        status.stats.signals_generated += 1

        self._logger.warning(
            f"Emergency stop-loss signal generated: "
            f"{signal.stock_id}, "
            f"qty={signal.quantity}, "
            f"price={signal.price_at_signal}, "
            f"stop_loss={signal.stop_loss_price}"
        )
