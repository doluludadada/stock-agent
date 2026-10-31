from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.account_snapshot import AccountSnapshot
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.valuation import AccountValuation, EquityPoint, ValuationRule
from b_application.config.app_config import AppConfig


@dataclass(frozen=True)
class AccountHistoryReport:
    current: AccountValuation
    """The account now, each position marked at its latest quote (realtime, else the last daily close)."""

    equity_curve: list[EquityPoint]

    as_of: tuple[AccountSnapshot, AccountValuation] | None
    """The account at the end of the requested day, or None when no fill happened on or before it."""


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
        self._history_days = config.freshness.history_max_lag_days
        self._logger = logger

    async def execute(self, as_of: date | None) -> AccountHistoryReport:
        account = await self._execution_provider.get_account()
        snapshots = await self._journal.snapshots()

        held_ids = {position.stock_id for position in account.positions}
        snapshot_ids = {held.stock_id for snapshot in snapshots for held in snapshot.positions}
        stocks = await self.load_stocks(held_ids | snapshot_ids)

        first_day = self._market_clock.today() - timedelta(days=self._history_days)

        if snapshots:
            first_day = min(first_day, self._market_clock.to_trading_date(snapshots[0].taken_at))

        daily_bars = await self.fetch_daily_bars(stocks, first_day)
        realtime_bars = await self.fetch_realtime_bars([stock for stock in stocks if stock.stock_id in held_ids])
        marks = {stock_id: bars[-1] for stock_id, bars in daily_bars.items() if bars} | realtime_bars

        trading_date = self._market_clock.to_trading_date

        return AccountHistoryReport(
            current=self._valuation_rule.value(account.cash, account.positions, marks),
            equity_curve=self._valuation_rule.equity_curve(snapshots, daily_bars, trading_date),
            as_of=None if as_of is None else self._valuation_rule.as_of(snapshots, daily_bars, as_of, trading_date),
        )

    async def load_stocks(self, stock_ids: set[str]) -> list[Stock]:
        stocks = []

        for stock_id in sorted(stock_ids):
            stock = await self._stock_provider.get_by_id(stock_id)

            if stock is None:
                self._logger.warning(f"Account history: stock not found: {stock_id}")
                continue

            stocks.append(stock)

        return stocks

    async def fetch_daily_bars(self, stocks: list[Stock], first_day: date) -> dict[str, list[Ohlcv]]:
        if not stocks:
            return {}

        now = self._market_clock.now()

        try:
            return await self._ohlcv_provider.fetch_history(stocks, datetime.combine(first_day, time.min, tzinfo=now.tzinfo), now)

        except Exception as error:
            self._logger.error(f"Account history: daily prices unavailable: {error}")
            return {}

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        if not stocks:
            return {}

        try:
            return await self._ohlcv_provider.fetch_realtime_bars(stocks)

        except Exception as error:
            self._logger.error(f"Account history: latest quotes unavailable: {error}")
            return {}
