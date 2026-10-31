from datetime import date, datetime, time

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.trading.account_history_report import AccountHistoryReport
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.valuation import (
    AccountAsOfRule,
    AccountHistoryRule,
    EquityCurveRule,
    PriceHistoryStartRule,
    SnapshotValuationRule,
    ValuationRule,
)
from b_application.config.app_config import AppConfig


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
        valuation_rule = ValuationRule(cost_rule=config.market.cost_rule())
        snapshot_valuation_rule = SnapshotValuationRule(valuation_rule=valuation_rule)
        self._history_rule = AccountHistoryRule(
            valuation_rule=valuation_rule,
            equity_curve_rule=EquityCurveRule(snapshot_valuation_rule=snapshot_valuation_rule),
            as_of_rule=AccountAsOfRule(snapshot_valuation_rule=snapshot_valuation_rule),
        )
        self._start_rule = PriceHistoryStartRule(history_days=config.freshness.history_max_lag_days)
        self._logger = logger

    async def execute(self, as_of: date | None) -> AccountHistoryReport:
        account = await self._execution_provider.get_account()
        snapshots = await self._journal.snapshots()
        held_ids = {position.stock_id for position in account.positions}
        stock_ids = sorted(held_ids | {held.stock_id for snapshot in snapshots for held in snapshot.positions})
        stocks = [stock for stock_id in stock_ids if (stock := await self._stock_provider.get_by_id(stock_id)) is not None]

        for stock_id in sorted(set(stock_ids) - {stock.stock_id for stock in stocks}):
            self._logger.warning(f"Account history: stock not found: {stock_id}")

        now = self._market_clock.now()
        first_day = self._start_rule.apply(self._market_clock.today(), snapshots, self._market_clock.to_trading_date)
        held = [stock for stock in stocks if stock.stock_id in held_ids]
        daily_bars: dict[str, list[Ohlcv]] = {}
        realtime_bars: dict[str, Ohlcv] = {}

        try:
            start = datetime.combine(first_day, time.min, tzinfo=now.tzinfo)
            daily_bars = await self._ohlcv_provider.fetch_history(stocks, start, now) if stocks else {}
        except Exception as error:
            self._logger.error(f"Account history: daily prices unavailable: {error}")

        try:
            realtime_bars = await self._ohlcv_provider.fetch_realtime_bars(held) if held else {}
        except Exception as error:
            self._logger.error(f"Account history: latest quotes unavailable: {error}")

        return self._history_rule.apply(account, snapshots, daily_bars, realtime_bars, as_of, self._market_clock.to_trading_date)
