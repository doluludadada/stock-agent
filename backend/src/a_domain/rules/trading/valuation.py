from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account
from a_domain.model.trading.account_history_report import AccountHistoryReport
from a_domain.model.trading.account_snapshot import AccountSnapshot
from a_domain.model.trading.account_valuation import AccountValuation
from a_domain.model.trading.equity_point import EquityPoint
from a_domain.model.trading.position import Position
from a_domain.model.trading.position_valuation import PositionValuation
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.types.enums import TradeAction


@dataclass(frozen=True)
class ValuationRule:
    """Marks positions to market. Realized and unrealized PnL share one formula: Position.profit_on_sale."""

    cost_rule: TradingCostRule

    def apply(self, cash: float, positions: Sequence[Position], marks: Mapping[str, Ohlcv]) -> AccountValuation:
        valuations = []

        for position in positions:
            mark = marks.get(position.stock_id)
            unrealized_pnl = 0.0

            if mark is not None:
                proceeds = self.cost_rule.apply(TradeAction.SELL, position.stock_id, mark.close, position.quantity, now=mark.ts).net
                unrealized_pnl = position.profit_on_sale(position.quantity, proceeds)

            valuations.append(PositionValuation(position=position, mark=mark, unrealized_pnl=unrealized_pnl))

        return AccountValuation(cash=cash, positions=valuations)


@dataclass(frozen=True)
class EquityRule:
    """
    The equity a run sizes its BUYs on: the cash plus each position at the latest price the run has for it (its realtime
    quote, else its last daily close, else its average cost), marked by ValuationRule as menu 7 marks it.
    """

    valuation_rule: ValuationRule

    def apply(self, account: Account, stocks: Iterable[Stock]) -> float:
        marks = {stock.stock_id: bar for stock in stocks if (bar := stock.latest_bar) is not None}

        return self.valuation_rule.apply(account.cash, account.positions, marks).equity


@dataclass(frozen=True)
class SnapshotValuationRule:
    """A snapshot's account marked at each stock's last daily close on or before `day`, else at its snapshot price."""

    valuation_rule: ValuationRule

    def apply(
        self, snapshot: AccountSnapshot, daily_bars: Mapping[str, Sequence[Ohlcv]], day: date, trading_date: Callable[[datetime], date]
    ) -> AccountValuation:
        marks = {}

        for held in snapshot.positions:
            closes = [bar for bar in daily_bars.get(held.stock_id, []) if trading_date(bar.ts) <= day]
            fallback = Ohlcv(
                ts=snapshot.taken_at, open=held.mark_price, high=held.mark_price, low=held.mark_price, close=held.mark_price
            )
            marks[held.stock_id] = max(closes, key=lambda bar: bar.ts) if closes else fallback

        positions = [
            Position(stock_id=held.stock_id, quantity=held.quantity, average_cost=held.average_cost) for held in snapshot.positions
        ]

        return self.valuation_rule.apply(snapshot.cash, positions, marks)


@dataclass(frozen=True)
class EquityCurveRule:
    """
    One point per trading day from the first snapshot on: the account of the day's last snapshot,
    marked at that day's closes. The trading days come from the price data, so no holiday calendar is needed.
    """

    snapshot_valuation_rule: SnapshotValuationRule

    def apply(
        self, snapshots: Sequence[AccountSnapshot], daily_bars: Mapping[str, Sequence[Ohlcv]], trading_date: Callable[[datetime], date]
    ) -> list[EquityPoint]:
        if not snapshots:
            return []

        snapshot_days = [(trading_date(snapshot.taken_at), snapshot) for snapshot in snapshots]
        first_day = snapshot_days[0][0]
        price_days = {trading_date(bar.ts) for bars in daily_bars.values() for bar in bars}
        days = sorted({day for day in price_days if day >= first_day} | {day for day, _ in snapshot_days})

        points = []

        for day in days:
            snapshot = [snapshot for snapshot_day, snapshot in snapshot_days if snapshot_day <= day][-1]
            valuation = self.snapshot_valuation_rule.apply(snapshot, daily_bars, day, trading_date)
            points.append(EquityPoint(day=day, cash=valuation.cash, market_value=valuation.market_value))

        return points


@dataclass(frozen=True)
class AccountAsOfRule:
    """The account as it stood at the end of `day`: its last snapshot on or before that day, marked at that day's closes."""

    snapshot_valuation_rule: SnapshotValuationRule

    def apply(
        self,
        snapshots: Sequence[AccountSnapshot],
        daily_bars: Mapping[str, Sequence[Ohlcv]],
        day: date,
        trading_date: Callable[[datetime], date],
    ) -> tuple[AccountSnapshot, AccountValuation] | None:
        earlier = [snapshot for snapshot in snapshots if trading_date(snapshot.taken_at) <= day]

        if not earlier:
            return None

        snapshot = earlier[-1]
        return snapshot, self.snapshot_valuation_rule.apply(snapshot, daily_bars, day, trading_date)


@dataclass(frozen=True)
class PriceHistoryStartRule:
    """The first day of daily prices the account history needs: `history_days` before today, or the first snapshot's day if earlier."""

    history_days: int

    def apply(self, today: date, snapshots: Sequence[AccountSnapshot], trading_date: Callable[[datetime], date]) -> date:
        first_day = today - timedelta(days=self.history_days)

        if not snapshots:
            return first_day

        return min(first_day, trading_date(snapshots[0].taken_at))


@dataclass(frozen=True)
class AccountHistoryRule:
    """
    The account history: the account now, each position marked at its latest quote (realtime, else the last daily
    close); one equity point per trading day since the first snapshot; and the account at the end of `as_of`, if asked.
    """

    valuation_rule: ValuationRule
    equity_curve_rule: EquityCurveRule
    as_of_rule: AccountAsOfRule

    def apply(
        self,
        account: Account,
        snapshots: Sequence[AccountSnapshot],
        daily_bars: Mapping[str, Sequence[Ohlcv]],
        realtime_bars: Mapping[str, Ohlcv],
        as_of: date | None,
        trading_date: Callable[[datetime], date],
    ) -> AccountHistoryReport:
        marks = {stock_id: bars[-1] for stock_id, bars in daily_bars.items() if bars} | dict(realtime_bars)

        return AccountHistoryReport(
            current=self.valuation_rule.apply(account.cash, account.positions, marks),
            equity_curve=self.equity_curve_rule.apply(snapshots, daily_bars, trading_date),
            as_of=None if as_of is None else self.as_of_rule.apply(snapshots, daily_bars, as_of, trading_date),
            live_stock_ids=frozenset(realtime_bars),
        )
