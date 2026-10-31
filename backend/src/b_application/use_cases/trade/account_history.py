from datetime import date

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.valuation import (
    AccountAsOfRule,
    EquityCurveRule,
    LatestMarkRule,
    PriceHistoryStartRule,
    SnapshotValuationRule,
    ValuationRule,
)
from b_application.config.app_config import AppConfig
from b_application.schemas.account_history_report import AccountHistoryReport


class AccountHistory:
    """
    Use Case: Read-only account history for CLI menu 7. It never places orders and records no run.

    Snapshots come from the trading journal (one after every fill); prices come from the market
    data provider. A price fetch that fails leaves positions valued at their snapshot or cost price.
    """

    def __init__(
        self,
        execution_provider: IExecutionProvider,
        journal: ITradingJournal,
        stock_provider: IStockProvider,
        ohlcv_provider: IOhlcvProvider,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._execution_provider = execution_provider
        self._journal = journal
        self._stock_provider = stock_provider
        self._ohlcv_provider = ohlcv_provider
        self._market_clock = market_clock
        self._valuation_rule = ValuationRule(cost_rule=config.market.cost_rule())
        snapshot_valuation_rule = SnapshotValuationRule(valuation_rule=self._valuation_rule)
        self._latest_mark_rule = LatestMarkRule()
        self._equity_curve_rule = EquityCurveRule(snapshot_valuation_rule=snapshot_valuation_rule)
        self._as_of_rule = AccountAsOfRule(snapshot_valuation_rule=snapshot_valuation_rule)
        self._start_rule = PriceHistoryStartRule(history_days=config.freshness.history_max_lag_days)
        self._logger = logger

    async def execute(self, as_of: date | None) -> AccountHistoryReport:
        account = await self._execution_provider.get_account()
        snapshots = await self._journal.snapshots()
        stock_ids = sorted(account.stock_ids | {held.stock_id for snapshot in snapshots for held in snapshot.positions})
        stocks = [stock for stock_id in stock_ids if (stock := await self._stock_provider.get_by_id(stock_id)) is not None]

        for stock_id in sorted(set(stock_ids) - {stock.stock_id for stock in stocks}):
            self._logger.warning(f"Account history: stock not found: {stock_id}")

        now = self._market_clock.now()
        start = self._start_rule.apply(now, snapshots, self._market_clock.to_trading_date)
        held = [stock for stock in stocks if stock.stock_id in account.stock_ids]
        daily_bars: dict[str, list[Ohlcv]] = {}
        realtime_bars: dict[str, Ohlcv] = {}

        try:
            daily_bars = await self._ohlcv_provider.fetch_history(stocks, start, now) if stocks else {}
        except Exception as error:
            self._logger.error(f"Account history: daily prices unavailable: {error}")

        try:
            realtime_bars = await self._ohlcv_provider.fetch_realtime_bars(held) if held else {}
        except Exception as error:
            self._logger.error(f"Account history: latest quotes unavailable: {error}")

        current = self._valuation_rule.apply(account.cash, account.positions, self._latest_mark_rule.apply(daily_bars, realtime_bars))
        equity_curve = self._equity_curve_rule.apply(snapshots, daily_bars, self._market_clock.to_trading_date)
        as_of_account = self._as_of_rule.apply(snapshots, daily_bars, as_of, self._market_clock.to_trading_date)

        return AccountHistoryReport(current, equity_curve, as_of_account, frozenset(realtime_bars))
