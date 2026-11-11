from bisect import bisect_left, bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta

import numpy as np
from pydantic import ConfigDict, Field, PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account, Position
from a_domain.model.trading.backtest import BacktestTrade
from a_domain.model.trading.signal import TradeSignal
from a_domain.rules.technical.matrix import DailyBarMatrix, StrategyScores
from a_domain.rules.trading.account_value import PositionValueRule
from a_domain.rules.trading.cost import AffordableQuantityRule, TradingCostRule
from a_domain.rules.trading.decision import RunDecisionsRule
from a_domain.rules.trading.exit import StopLossRule
from a_domain.types.enums import SignalSource, TradeAction
from a_domain.types.errors import BacktestPeriodUnavailable
from a_domain.types.values import Score


@dataclass(frozen=True)
class DailyBarMatrixRule:
    """Every stock's daily bars as one matrix: the stocks in id order, and one column per session any of them traded."""

    def apply(self, history: Mapping[str, Sequence[Ohlcv]], trading_date: Callable[[datetime], date]) -> DailyBarMatrix:
        days = {stamp: trading_date(stamp) for stamp in {bar.ts for bars in history.values() for bar in bars}}
        sessions = tuple(sorted(set(days.values())))
        columns = {session: column for column, session in enumerate(sessions)}
        stock_ids = tuple(sorted(history))
        cells = {name: np.full((len(stock_ids), len(sessions)), np.nan) for name in ("open", "high", "low", "close", "volume")}

        for row, stock_id in enumerate(stock_ids):
            held = [columns[days[bar.ts]] for bar in history[stock_id]]

            for name, values in cells.items():
                values[row, held] = [getattr(bar, name) for bar in history[stock_id]]

        return DailyBarMatrix(stock_ids=stock_ids, sessions=sessions, **cells)


@dataclass(frozen=True)
class BacktestPeriodRule:
    """
    The first and the last day a backtest may cover, or None when it may cover none. A run reads `history_days`
    calendar days of daily history before its day, so a backtest starts no earlier than that many days after the first
    session held, and ends at the last session held.
    """

    def apply(self, first_held: date, last_held: date, history_days: int) -> tuple[date, date] | None:
        first = first_held + timedelta(days=history_days)

        return (first, last_held) if first <= last_held else None


@dataclass(frozen=True)
class BacktestHistoryRule:
    """
    The bars a backtest from `first` to `last` reads: the columns from the start of its first session's history window
    to its last session, and for each of them the column where its own history window starts. A period that reaches
    outside what BacktestPeriodRule allows, or that holds no session, raises BacktestPeriodUnavailable, which says what
    a backtest may cover.
    """

    period_rule: BacktestPeriodRule

    def apply(self, bars: DailyBarMatrix, first: date, last: date, history_days: int) -> tuple[DailyBarMatrix, list[int]]:
        held = (
            f"the daily history holds {bars.sessions[0]} to {bars.sessions[-1]}, "
            f"and a backtest reads {history_days} days before its first day"
        )
        available = self.period_rule.apply(bars.sessions[0], bars.sessions[-1], history_days)
        covered = [session for session in bars.sessions if first <= session <= last]

        if available is None:
            raise BacktestPeriodUnavailable(f"No backtest can run yet: {held}.")

        if first < available[0] or last > available[1] or not covered:
            raise BacktestPeriodUnavailable(
                f"A backtest can cover {available[0]} to {available[1]}, and {first} to {last} "
                f"{'reaches outside it' if covered else 'holds no session'}: {held}."
            )

        window = timedelta(days=history_days)
        start, end = bisect_left(bars.sessions, covered[0] - window), bisect_right(bars.sessions, last)
        history = replace(
            bars,
            sessions=bars.sessions[start:end],
            **{name: getattr(bars, name)[:, start:end] for name in ("open", "high", "low", "close", "volume")},
        )

        return history, [bisect_left(history.sessions, session - window) for session in history.sessions]


@dataclass(frozen=True)
class OpenFillRule:
    """
    What a decision made after one session's close fills at the open of a later session, as (shares, price), or None
    when it does not fill there. Nothing trades without a bar. A bar of one price is a locked limit: a BUY never fills
    on one, and a SELL does not fill on one below the previous close, where nobody buys. A BUY takes the decided shares,
    capped by what the cash pays for at the open, fee included.
    """

    lot_size: PositiveInt
    affordable_quantity_rule: AffordableQuantityRule

    def apply(
        self, signal: TradeSignal, bar: Ohlcv | None, previous_close: float, cash: float, *, now: datetime
    ) -> tuple[int, float] | None:
        if bar is None:
            return None

        if signal.action == TradeAction.SELL:
            return None if bar.high == bar.low and bar.open < previous_close else (signal.quantity, bar.open)

        if bar.high == bar.low:
            return None

        affordable = self.affordable_quantity_rule.apply(
            cash=cash, stock_id=signal.stock_id, price=bar.open, lot_size=self.lot_size, now=now
        )
        quantity = min(signal.quantity, affordable)

        return (quantity, bar.open) if quantity else None


@dataclass(frozen=True)
class SessionStopLossRule:
    """
    The price a held position's stop-loss fills at inside a session, or None when it does not: StopLossRule on the
    session's low, the worst quote of the day. It fills at the stop-loss price, or at the open when the stock opened
    below it. A bar of one price below the previous close is a locked limit-down, where nothing sells.
    """

    stop_loss_rule: StopLossRule

    def apply(self, position: Position, bar: Ohlcv, previous_close: float, *, now: datetime) -> float | None:
        if bar.high == bar.low and bar.open < previous_close:
            return None

        at_the_low = Stock(stock_id=position.stock_id, realtime_bar=replace(bar, close=bar.low))
        signal = self.stop_loss_rule.apply(at_the_low, position, now=now)

        if signal is None or signal.stop_loss_price is None:
            return None

        return min(bar.open, signal.stop_loss_price)


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class BacktestBook:
    """What BacktestRule reads and keeps from session to session."""

    bars: DailyBarMatrix
    names: Mapping[str, str | None]
    rows: dict[str, int]
    """Each stock's row of `bars`."""

    last_close: np.ndarray
    """Each stock's latest close at or before each session: a stock without a bar keeps its last one."""

    account: Account
    pending: list[TradeSignal] = Field(default_factory=list)
    """The decisions waiting for an open: every BUY and SELL of the last close, and the older SELLs that could not fill."""

    opened: dict[str, int] = Field(default_factory=dict)
    """The column of the first BUY of each held stock."""

    fees: dict[str, int] = Field(default_factory=dict)
    """The BUY fees paid so far on each held stock."""

    trades: list[BacktestTrade] = Field(default_factory=list)


@dataclass(frozen=True)
class BacktestRule:
    """
    Replays a strategy's scores day by day on an account that starts with cash alone, and returns the account at each
    session's close from `first` on and every trade. No decision reads a bar after its own session:

    - At the open, the SELLs waiting fill first, then the BUYs of the last close in decision order (OpenFillRule). A
      SELL that cannot fill waits for the next open; a BUY that cannot fill is dropped.
    - Inside the session, each held position's stop-loss is checked on the low (SessionStopLossRule), a position
      bought at that open included. What it frees is cash for the next session's BUYs.
    - A SELL of so few shares that its fee and tax exceed what it brings, on an account without the cash to pay the
      difference, does not fill: the account never owes. The position stays, and its SELL or stop-loss comes again.
    - At the close, the account is marked at each stock's latest close (PositionValueRule), and RunDecisionsRule, the
      live decisions, decides on that equity for every held stock with a bar and every stock that passed the strategy
      with at least `buy_score`: no other stock can get anything but a HOLD. The composite score is the technical
      score. A stock whose SELL is waiting gets no new decision.

    The last session decides nothing, since no later open could fill it. A position still held then is a trade still
    open, with the PnL of selling it at that close. The prices are the adjusted daily history, so a fill price is not
    rounded to the exchange's tick.
    """

    buy_score: Score[int]
    run_decisions_rule: RunDecisionsRule
    open_fill_rule: OpenFillRule
    session_stop_loss_rule: SessionStopLossRule
    cost_rule: TradingCostRule
    position_value_rule: PositionValueRule

    def apply(
        self,
        bars: DailyBarMatrix,
        scores: StrategyScores,
        names: Mapping[str, str | None],
        first: date,
        initial_cash: float,
        session_close: Callable[[date], datetime],
    ) -> tuple[dict[date, Account], list[BacktestTrade]]:
        rows = {stock_id: row for row, stock_id in enumerate(bars.stock_ids)}
        book = BacktestBook(bars=bars, names=names, rows=rows, last_close=last_closes(bars.close), account=Account(cash=initial_cash))
        curve: dict[date, Account] = {}
        last = len(bars.sessions) - 1

        for column in range(bisect_left(bars.sessions, first), last + 1):
            now = session_close(bars.sessions[column])
            self._fill_at_the_open(book, column, now)
            self._check_stop_losses(book, column, now)
            curve[bars.sessions[column]] = marked = self._marked(book, column, now)

            if column < last:
                book.pending += self._decide(book, scores, column, marked.equity, now)

        closing = curve[bars.sessions[last]]
        still_open = [self._trade(book, position, last, position.unrealized_pnl) for position in closing.positions]

        return curve, book.trades + still_open

    def _fill_at_the_open(self, book: BacktestBook, column: int, now: datetime) -> None:
        waiting: list[TradeSignal] = []

        for signal in sorted(book.pending, key=lambda signal: signal.action != TradeAction.SELL):
            row, held = book.rows[signal.stock_id], book.account.position_for(signal.stock_id)
            bar, previous_close = session_bar(book.bars, row, column, now), book.last_close[row, column - 1]
            fill = self.open_fill_rule.apply(signal, bar, previous_close, book.account.cash, now=now)

            if fill is not None and signal.action == TradeAction.BUY:
                self._buy(book, signal.stock_id, *fill, column, now)
            elif held is not None and (fill is None or not self._sell(book, held, fill[1], signal.source, column, now)):
                waiting.append(signal)

        book.pending = waiting

    def _check_stop_losses(self, book: BacktestBook, column: int, now: datetime) -> None:
        waiting = {signal.stock_id for signal in book.pending}

        for position in list(book.account.positions):
            row = book.rows[position.stock_id]
            bar = session_bar(book.bars, row, column, now)

            if bar is None or position.stock_id in waiting:
                continue

            price = self.session_stop_loss_rule.apply(position, bar, book.last_close[row, column - 1], now=now)

            if price is not None:
                self._sell(book, position, price, SignalSource.STOP_LOSS, column, now)

    def _buy(self, book: BacktestBook, stock_id: str, quantity: int, price: float, column: int, now: datetime) -> None:
        cost = self.cost_rule.apply(TradeAction.BUY, stock_id, price, quantity, now=now)
        book.account.buy(stock_id, quantity, price, -cost.net)
        book.opened.setdefault(stock_id, column)
        book.fees[stock_id] = book.fees.get(stock_id, 0) + cost.fee

    def _sell(self, book: BacktestBook, position: Position, price: float, source: SignalSource, column: int, now: datetime) -> bool:
        """Whether the position was sold. The fee can exceed what a few shares bring: a sale the cash cannot pay for does not fill."""
        cost = self.cost_rule.apply(TradeAction.SELL, position.stock_id, price, position.quantity, now=now)

        if book.account.cash + cost.net < 0:
            return False

        pnl = position.profit_on_sale(position.quantity, cost.net)
        book.fees[position.stock_id] += cost.fee
        trade = self._trade(book, position, column, pnl)
        book.trades.append(replace(trade, sold_on=book.bars.sessions[column], sold_at=price, exit_source=source, tax=cost.tax))
        book.account.sell(position.stock_id, position.quantity, cost.net)
        del book.opened[position.stock_id], book.fees[position.stock_id]

        return True

    def _trade(self, book: BacktestBook, position: Position, column: int, pnl: float) -> BacktestTrade:
        """The position's trade as it stands at `column`, still open: its PnL is `pnl`, and its fees those paid so far."""
        opened = book.opened[position.stock_id]

        return BacktestTrade(
            stock_id=position.stock_id,
            stock_name=book.names.get(position.stock_id),
            quantity=position.quantity,
            bought_on=book.bars.sessions[opened],
            average_cost=position.average_cost,
            pnl=pnl,
            fee=book.fees[position.stock_id],
            tax=0,
            held_sessions=column - opened,
        )

    def _marked(self, book: BacktestBook, column: int, now: datetime) -> Account:
        positions = [
            self.position_value_rule.apply(position, book.last_close[book.rows[position.stock_id], column], now)
            for position in book.account.positions
        ]

        return replace(book.account, positions=positions)

    def _decide(self, book: BacktestBook, scores: StrategyScores, column: int, equity: float, now: datetime) -> list[TradeSignal]:
        buyable = np.flatnonzero(scores.passed[:, column] & (scores.score[:, column] >= self.buy_score))
        held = {book.rows[stock_id] for stock_id in book.account.stock_ids}
        waiting = {book.rows[signal.stock_id] for signal in book.pending}
        stocks = [
            Stock(
                stock_id=book.bars.stock_ids[row],
                name=book.names.get(book.bars.stock_ids[row]),
                ohlcv=[bar],
                technical_report=TechnicalReport(
                    score=int(scores.score[row, column]), hard_failures=[] if scores.passed[row, column] else ["Failed the strategy"]
                ),
                composite_score=int(scores.score[row, column]),
            )
            for row in sorted({*buyable.tolist(), *held} - waiting)
            if (bar := session_bar(book.bars, row, column, now)) is not None
        ]
        signals = self.run_decisions_rule.apply(stocks, book.account, equity, now=now)

        return [signal for signal in signals if signal.action != TradeAction.HOLD]


def last_closes(close: np.ndarray) -> np.ndarray:
    """Each row's latest value at or before each column: NaN only before the row's first value."""
    columns = np.where(np.isnan(close), 0, np.arange(close.shape[1]))
    np.maximum.accumulate(columns, axis=1, out=columns)

    return np.take_along_axis(close, columns, axis=1)


def session_bar(bars: DailyBarMatrix, row: int, column: int, at: datetime) -> Ohlcv | None:
    """The stock's bar of the session, stamped `at`, or None when it has none."""
    if np.isnan(bars.close[row, column]):
        return None

    return Ohlcv(
        ts=at,
        open=bars.open[row, column],
        high=bars.high[row, column],
        low=bars.low[row, column],
        close=bars.close[row, column],
        volume=int(bars.volume[row, column]),
    )
