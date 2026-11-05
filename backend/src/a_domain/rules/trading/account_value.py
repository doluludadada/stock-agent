from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import date, datetime, time, timedelta

from pydantic.dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account, AccountSnapshot, Mark, Position
from a_domain.model.trading.order import Order
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.types.enums import TradeAction


@dataclass(frozen=True)
class PositionValueRule:
    """
    One position valued at `price`, quoted at `at`: a new Position whose mark carries the PnL of selling it all there,
    with that day's SELL fee and tax deducted. Realized and unrealized PnL share one formula: Position.profit_on_sale.
    """

    cost_rule: TradingCostRule

    def apply(self, position: Position, price: float, at: datetime) -> Position:
        proceeds = self.cost_rule.apply(TradeAction.SELL, position.stock_id, price, position.quantity, now=at).net
        pnl = position.profit_on_sale(position.quantity, proceeds)

        return replace(position, mark=Mark(price=price, at=at, unrealized_pnl=pnl))


@dataclass(frozen=True)
class AccountValueRule:
    """
    The account valued at the latest price the run has for each position: Stock.latest_bar, its realtime quote, else
    its last daily close. A position whose stock has neither has no mark and counts at its average cost. A run sizes
    its BUYs on this account's equity, and menu 7 shows it as the account now. It returns a new Account and changes
    neither the account nor its positions, which the run still holds.
    """

    position_value_rule: PositionValueRule

    def apply(self, account: Account, stocks: Iterable[Stock]) -> Account:
        bars = {stock.stock_id: bar for stock in stocks if (bar := stock.latest_bar) is not None}
        positions = [
            replace(position, mark=None)
            if (bar := bars.get(position.stock_id)) is None
            else self.position_value_rule.apply(position, bar.close, bar.ts)
            for position in account.positions
        ]

        return replace(account, positions=positions)


@dataclass(frozen=True)
class SnapshotValueRule:
    """
    A snapshot's account valued at the end of `day`: each position at its stock's last daily close on or before that
    day, else at its snapshot price (Position.mark_price) stamped at the snapshot's time. A position whose stock was
    not found keeps its snapshot price.
    """

    position_value_rule: PositionValueRule

    def apply(
        self, snapshot: AccountSnapshot, stocks: Sequence[Stock], day: date, trading_date: Callable[[datetime], date]
    ) -> Account:
        history = {stock.stock_id: stock.ohlcv for stock in stocks}
        positions = []

        for position in snapshot.account.positions:
            closes = [bar for bar in history.get(position.stock_id, []) if trading_date(bar.ts) <= day]
            close = max(closes, key=lambda bar: bar.ts) if closes else None
            price, at = (close.close, close.ts) if close else (position.mark_price, snapshot.taken_at)
            positions.append(self.position_value_rule.apply(position, price, at))

        return replace(snapshot.account, positions=positions)


@dataclass(frozen=True)
class FillSnapshotRule:
    """
    The account right after `order` filled, at `taken_at`: the filled stock marked at its fill price, every other
    position at the run's latest price in `stocks` (Stock.latest_bar), else without a mark. SnapshotValueRule values
    a snapshot again whenever it is shown, so the snapshot's marks carry no PnL.
    """

    def apply(self, order: Order, account: Account, stocks: Iterable[Stock], taken_at: datetime) -> AccountSnapshot:
        marks = {stock.stock_id: Mark(price=bar.close, at=bar.ts) for stock in stocks if (bar := stock.latest_bar) and bar.close}
        fill_price = order.average_filled_price or order.limit_price

        if fill_price is not None:
            marks[order.stock_id] = Mark(price=fill_price, at=taken_at)

        positions = [replace(position, mark=marks.get(position.stock_id)) for position in account.positions]

        return AccountSnapshot(
            taken_at=taken_at, run_id=order.run_id, order_id=order.id, account=replace(account, positions=positions)
        )


@dataclass(frozen=True)
class AccountAsOfRule:
    """
    The account as it stood at the end of `day`: its last snapshot on or before that day, with the snapshot's account
    valued at that day's closes. None when no day is asked or no fill happened on or before it.
    """

    snapshot_value_rule: SnapshotValueRule

    def apply(
        self, snapshots: Sequence[AccountSnapshot], stocks: Sequence[Stock], day: date | None, trading_date: Callable[[datetime], date]
    ) -> AccountSnapshot | None:
        if day is None:
            return None

        earlier = [snapshot for snapshot in snapshots if trading_date(snapshot.taken_at) <= day]

        if not earlier:
            return None

        snapshot = earlier[-1]
        return replace(snapshot, account=self.snapshot_value_rule.apply(snapshot, stocks, day, trading_date))


@dataclass(frozen=True)
class EquityCurveRule:
    """
    The account at the end of each trading day from the first snapshot on, in day order, as AccountAsOfRule gives it
    for that day. The trading days come from the stocks' daily history, so no holiday calendar is needed.
    """

    as_of_rule: AccountAsOfRule

    def apply(
        self, snapshots: Sequence[AccountSnapshot], stocks: Sequence[Stock], trading_date: Callable[[datetime], date]
    ) -> dict[date, Account]:
        if not snapshots:
            return {}

        snapshot_days = {trading_date(snapshot.taken_at) for snapshot in snapshots}
        first_day = trading_date(snapshots[0].taken_at)
        price_days = {trading_date(bar.ts) for stock in stocks for bar in stock.ohlcv}
        days = sorted({day for day in price_days if day >= first_day} | snapshot_days)

        return {
            day: as_of.account for day in days if (as_of := self.as_of_rule.apply(snapshots, stocks, day, trading_date)) is not None
        }


@dataclass(frozen=True)
class PriceHistoryStartRule:
    """
    Where the daily prices the account history needs start: midnight, in `now`'s zone, of the day `history_days`
    before the trading day of `now`, or of the first snapshot's day if earlier.
    """

    history_days: int

    def apply(self, now: datetime, snapshots: Sequence[AccountSnapshot], trading_date: Callable[[datetime], date]) -> datetime:
        first_day = trading_date(now) - timedelta(days=self.history_days)

        if snapshots:
            first_day = min(first_day, trading_date(snapshots[0].taken_at))

        return datetime.combine(first_day, time.min, tzinfo=now.tzinfo)
