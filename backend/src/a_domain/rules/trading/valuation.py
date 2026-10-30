from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.trading.account_snapshot import AccountSnapshot
from a_domain.model.trading.position import Position
from a_domain.rules.trading.cost import TradingCostRule
from a_domain.types.enums import TradeAction


@dataclass(frozen=True)
class PositionValuation:
    position: Position
    mark: Ohlcv | None
    """The bar whose close prices the position; its ts is the price time shown. None: no price, valued at average cost."""

    unrealized_pnl: float
    """Net proceeds of selling everything at the mark (fee and tax deducted) minus the cost basis. 0 when unmarked."""

    @property
    def market_value(self) -> float:
        return self.position.quantity * (self.mark.close if self.mark else self.position.average_cost)


@dataclass(frozen=True)
class AccountValuation:
    cash: float
    positions: list[PositionValuation]

    @property
    def market_value(self) -> float:
        return sum(position.market_value for position in self.positions)

    @property
    def unrealized_pnl(self) -> float:
        return sum(position.unrealized_pnl for position in self.positions)

    @property
    def equity(self) -> float:
        return self.cash + self.market_value


@dataclass(frozen=True)
class EquityPoint:
    day: date
    cash: float
    market_value: float

    @property
    def equity(self) -> float:
        return self.cash + self.market_value


@dataclass(frozen=True)
class ValuationRule:
    """Marks positions to market. Realized and unrealized PnL share one formula: Position.profit_on_sale."""

    cost_rule: TradingCostRule

    def value(self, cash: float, positions: Sequence[Position], marks: Mapping[str, Ohlcv]) -> AccountValuation:
        valuations = []

        for position in positions:
            mark = marks.get(position.stock_id)
            unrealized_pnl = 0.0

            if mark is not None:
                proceeds = self.cost_rule.cost_of(TradeAction.SELL, mark.close, position.quantity).net
                unrealized_pnl = position.profit_on_sale(position.quantity, proceeds)

            valuations.append(PositionValuation(position=position, mark=mark, unrealized_pnl=unrealized_pnl))

        return AccountValuation(cash=cash, positions=valuations)

    def value_snapshot(
        self, snapshot: AccountSnapshot, daily_bars: Mapping[str, Sequence[Ohlcv]], day: date, trading_date: Callable[[datetime], date]
    ) -> AccountValuation:
        """The snapshot's account marked at each stock's last daily close on or before `day`, else at its snapshot price."""
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

        return self.value(snapshot.cash, positions, marks)

    def equity_curve(
        self, snapshots: Sequence[AccountSnapshot], daily_bars: Mapping[str, Sequence[Ohlcv]], trading_date: Callable[[datetime], date]
    ) -> list[EquityPoint]:
        """
        One point per trading day from the first snapshot on: the account of the day's last snapshot,
        marked at that day's closes. The trading days come from the price data, so no holiday calendar is needed.
        """
        if not snapshots:
            return []

        snapshot_days = [(trading_date(snapshot.taken_at), snapshot) for snapshot in snapshots]
        first_day = snapshot_days[0][0]
        price_days = {trading_date(bar.ts) for bars in daily_bars.values() for bar in bars}
        days = sorted({day for day in price_days if day >= first_day} | {day for day, _ in snapshot_days})

        points = []

        for day in days:
            snapshot = [snapshot for snapshot_day, snapshot in snapshot_days if snapshot_day <= day][-1]
            valuation = self.value_snapshot(snapshot, daily_bars, day, trading_date)
            points.append(EquityPoint(day=day, cash=valuation.cash, market_value=valuation.market_value))

        return points

    def as_of(
        self,
        snapshots: Sequence[AccountSnapshot],
        daily_bars: Mapping[str, Sequence[Ohlcv]],
        day: date,
        trading_date: Callable[[datetime], date],
    ) -> tuple[AccountSnapshot, AccountValuation] | None:
        """The account as it stood at the end of `day`: its last snapshot on or before that day, marked at that day's closes."""
        earlier = [snapshot for snapshot in snapshots if trading_date(snapshot.taken_at) <= day]

        if not earlier:
            return None

        snapshot = earlier[-1]
        return snapshot, self.value_snapshot(snapshot, daily_bars, day, trading_date)
