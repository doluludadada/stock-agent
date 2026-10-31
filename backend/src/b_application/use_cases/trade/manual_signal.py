from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import TradeAction
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class ManualSignal:
    """
    Use Case: Decides and records the user's confirmed BUY of one stock with ManualEntryRule, which skips the
    buy threshold but never the sizing on the run's equity. When there is no price, the decision cannot be recorded,
    or it sizes to no share, status.manual_buy_refusal says why and no orderable decision reaches the run's signals.
    """

    def __init__(self, journal: ITradingJournal, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._market_clock = market_clock
        self._entry_rule = config.manual_entry_rule()
        self._logger = logger

    async def execute(self, stock: Stock, status: PipelineStatus) -> None:
        if stock.current_price is None:
            status.manual_buy_refusal = "no price: the realtime quote and the daily history are both unavailable"
            self._logger.warning(f"Manual BUY {stock.stock_id} not placed: {status.manual_buy_refusal}")
            return

        signal = self._entry_rule.apply(stock, status.account, equity=status.require_equity(), now=self._market_clock.now())

        try:
            await self._journal.save_signals(status.stats.run_id, [signal])

        except Exception as error:
            status.stats.add_error(f"Manual BUY decision not saved: {error}")
            status.manual_buy_refusal = f"the decision could not be recorded, so no order was sent: {error}"
            self._logger.warning(f"Manual BUY {stock.stock_id} not placed: {status.manual_buy_refusal}")
            return

        status.signals.append(signal)
        status.stats.signals_generated += 1

        if signal.action == TradeAction.HOLD:
            status.manual_buy_refusal = signal.reason
            self._logger.warning(f"Manual BUY {stock.stock_id} not placed: {status.manual_buy_refusal}")
