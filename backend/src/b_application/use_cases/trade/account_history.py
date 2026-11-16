from datetime import date

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account, AccountSnapshot
from a_domain.ports.market.price_provider import IPriceHistoryProvider, IQuoteBoard
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.account_value import AccountAsOfRule, EquityCurveRule, PriceHistoryStartRule, SnapshotValueRule
from b_application.config.app_config import AppConfig


class AccountHistory:
    """
    Use Case: Read-only account history for menu 7 and GET /v1/account/history. It never places orders and records no
    run.

    Snapshots come from the trading journal: one after every fill of a run on this broker, since the mock account
    opened, every one at a real broker. Daily prices come from the price history, and today's quote of each held stock
    from the board the pages share, as it holds it: this step asks the quote source nothing, so the account is valued
    at a quote only once a page's own request made the board read it (PageQuotes). Both are loaded into the Stock
    objects it returns. A price fetch that fails leaves positions valued at their snapshot or cost price. It returns
    the account valued now, the held stocks, the equity curve, which today's quotes end, and the account as of `as_of`.
    With `since` it reads the daily prices and answers the curve from that day on only, which is what a page that
    already holds the curve asks for when a quote moved: every day of the curve is valued, so the whole curve of an
    old account is slow to answer.
    """

    def __init__(
        self,
        execution_provider: IExecutionProvider,
        journal: ITradingJournal,
        stock_provider: IStockProvider,
        price_history: IPriceHistoryProvider,
        quote_board: IQuoteBoard,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._execution_provider = execution_provider
        self._journal = journal
        self._stock_provider = stock_provider
        self._price_history = price_history
        self._quote_board = quote_board
        self._market_clock = market_clock
        self._value_rule = config.market.account_value_rule()
        self._as_of_rule = AccountAsOfRule(
            snapshot_value_rule=SnapshotValueRule(position_value_rule=config.market.position_value_rule())
        )
        self._equity_curve_rule = EquityCurveRule(as_of_rule=self._as_of_rule)
        self._start_rule = PriceHistoryStartRule(history_days=config.freshness.history_max_lag_days)
        self._logger = logger

    async def execute(
        self, as_of: date | None, since: date | None
    ) -> tuple[Account, list[Stock], dict[date, Account], AccountSnapshot | None]:
        account = await self._execution_provider.get_account()
        snapshots = await self._journal.snapshots(self._execution_provider.link().broker, account.opened_at)
        stock_ids = sorted(account.stock_ids.union(*(snapshot.account.stock_ids for snapshot in snapshots)))
        stocks = [stock for stock_id in stock_ids if (stock := await self._stock_provider.get_by_id(stock_id)) is not None]

        for stock_id in sorted(set(stock_ids) - {stock.stock_id for stock in stocks}):
            self._logger.warning(f"Account history: stock not found: {stock_id}")

        now, trading_date = self._market_clock.now(), self._market_clock.to_trading_date
        start = self._start_rule.apply(now, snapshots, since, trading_date)
        held = [stock for stock in stocks if stock.stock_id in account.stock_ids]
        daily_bars: dict[str, list[Ohlcv]] = {}

        try:
            daily_bars = await self._price_history.fetch_history(stocks, start, now) if stocks else {}
        except Exception as error:
            self._logger.error(f"Account history: daily prices unavailable: {error}")

        quotes = self._quote_board.quotes(account.stock_ids, trading_date(now))

        for stock in stocks:
            stock.load_history(daily_bars.get(stock.stock_id, []))
            stock.realtime_bar = quotes.get(stock.stock_id)

        curve = self._equity_curve_rule.apply(snapshots, stocks, since, trading_date)
        return self._value_rule.apply(account, held), held, curve, self._as_of_rule.apply(snapshots, stocks, as_of, trading_date)
