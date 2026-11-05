from collections.abc import Mapping

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.exit import BlockedStockRule, StopLossQuoteRule
from b_application.config.app_config import AppConfig


class AccountRiskCheck:
    """
    Use Case: Fixes the run's equity, then runs the fast account-level stop-loss check.

    The equity is the account's cash plus each position at the latest price the run has loaded for it (AccountValueRule).
    It is fixed here, before the run's first decision and before any stop-loss SELL fills, and every automatic BUY of
    the run takes its risk budget from it.

    The check runs after AccountLoader and the realtime refresh, and the workflow sends the stop-loss SELLs it records
    right away, while their quotes are fresh. It only checks emergency stop-loss, on held stocks whose quote
    StopLossQuoteRule accepts, so it cannot fire without a realtime quote. It returns the equity, each stock it decided
    to sell (its decision saved or not, so the run decides nothing else for it) and the SELLs it recorded.
    """

    def __init__(self, journal: ITradingJournal, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._market_clock = market_clock
        self._value_rule = config.market.account_value_rule()
        self._quote_rule = StopLossQuoteRule(blocked_rule=BlockedStockRule())
        self._stop_loss_rule = config.stop_loss_rule()
        self._logger = logger

    async def execute(
        self, account: Account, held_stocks: list[Stock], stocks: Mapping[str, Stock], stale_stock_ids: set[str], stats: SystemStats
    ) -> tuple[float, set[str], list[TradeSignal]]:
        equity = self._value_rule.apply(account, stocks.values()).equity
        self._logger.info(f"Equity fixed for sizing: {equity:,.0f}, of which cash {account.cash:,.0f}.")
        risk_blocked_stock_ids: set[str] = set()
        signals: list[TradeSignal] = []

        for stock in held_stocks:
            if (skip := self._quote_rule.apply(stock, risk_blocked_stock_ids, stale_stock_ids)) is not None:
                self._logger.info(f"Risk check skipped. {skip}: {stock.stock_id}")
                continue

            position = account.position_for(stock.stock_id)
            signal = None if position is None else self._stop_loss_rule.apply(stock, position, now=self._market_clock.now())
            if signal is None:
                continue

            risk_blocked_stock_ids.add(signal.stock_id)
            try:
                await self._journal.save_signals(stats.run_id, [signal])
            except Exception as error:
                message = f"Stop-loss signal persistence failed, so it is not acted on: {signal.stock_id}, error={error}"
                self._logger.error(stats.add_error(message))
                continue
            signals.append(signal)
            stats.signals_generated += 1
            self._logger.warning(f"Stop-loss SELL recorded: {signal.stock_id}, qty={signal.quantity}, price={signal.price_at_signal}")

        return equity, risk_blocked_stock_ids, signals
