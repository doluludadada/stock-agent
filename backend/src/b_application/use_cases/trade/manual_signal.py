from collections.abc import Mapping

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.enums import TradeAction
from b_application.config.app_config import AppConfig


class ManualSignal:
    """
    Use Case: Decides and records the user's confirmed BUY of one analysed stock with ManualEntryRule, which skips the
    buy threshold but never the sizing on the run's equity: the account's cash plus each position at the run's latest
    price for it (AccountValueRule). It returns the recorded decision and, when no order may follow, why: the analysis has no
    composite score, there is no price, the decision cannot be recorded, or it sizes to no share.
    """

    def __init__(self, journal: ITradingJournal, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._market_clock = market_clock
        self._value_rule = config.market.account_value_rule()
        self._entry_rule = config.manual_entry_rule()
        self._logger = logger

    async def execute(
        self, stock: Stock, account: Account, stocks: Mapping[str, Stock], stats: SystemStats
    ) -> tuple[list[TradeSignal], str | None]:
        refusal = None

        if stock.composite_score is None:
            refusal = "analysis incomplete: no composite score"
        elif stock.current_price is None:
            refusal = "no price: the realtime quote and the daily history are both unavailable"

        if refusal is not None:
            self._logger.warning(f"Manual BUY {stock.stock_id} not placed: {refusal}")
            return [], refusal

        equity = self._value_rule.apply(account, stocks.values()).equity
        signal = self._entry_rule.apply(stock, account, equity=equity, now=self._market_clock.now())

        try:
            await self._journal.save_signals(stats.run_id, [signal])
        except Exception as error:
            stats.add_error(f"Manual BUY decision not saved: {error}")
            refusal = f"the decision could not be recorded, so no order was sent: {error}"
            self._logger.warning(f"Manual BUY {stock.stock_id} not placed: {refusal}")
            return [], refusal

        stats.signals_generated += 1
        refusal = signal.reason if signal.action == TradeAction.HOLD else None
        self._logger.info(f"Manual BUY {stock.stock_id} decided: {signal.action.value}, equity {equity:,.0f}, refusal {refusal}.")

        return [signal], refusal
