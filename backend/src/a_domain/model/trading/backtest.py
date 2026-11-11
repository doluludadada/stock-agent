from datetime import date, datetime
from typing import Annotated, Self

from pydantic import ConfigDict, Field, FiniteFloat, NonNegativeInt, PositiveInt, computed_field, model_validator
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.trading.account import Account
from a_domain.types.enums import SearchLevel, SignalSource
from a_domain.types.ids import BacktestId, new_backtest_id
from a_domain.types.values import FormulaId, NonEmptyText, PositiveFiniteFloat, ProperFraction, Score


@dataclass(frozen=True, kw_only=True, config=ConfigDict(use_attribute_docstrings=True))
class BacktestInputs:
    """What a user chooses for one backtest: the period, the cash it starts with and the scores that buy and sell."""

    first: date
    last: date
    """The backtest covers every session from `first` to `last`, both included."""

    initial_cash: PositiveFiniteFloat
    buy_score: Score[int]
    """A stock that passes the strategy with at least this score is bought: analysis.min_combined_score_buy in a run."""

    sell_score: Score[int]
    """A held stock at or below this score is sold: analysis.max_combined_score_sell in a run."""

    @model_validator(mode="after")
    def _first_is_not_after_last(self) -> Self:
        if self.first > self.last:
            raise ValueError("first must not be after last")

        return self


@dataclass(frozen=True, kw_only=True, config=ConfigDict(use_attribute_docstrings=True))
class SearchInputs:
    """What a user chooses for one strategy search, which breeds strategies from a built-in one by backtesting them."""

    strategy_id: FormulaId
    """The built-in strategy the search starts from."""

    level: SearchLevel
    random_seed: int
    """The same inputs and seed on the same history breed the same candidates."""

    population: PositiveInt
    """New candidates per generation, and the fittest so far kept to breed them from."""

    generations: NonNegativeInt
    buy_score: Score[int]
    """The score the strategy it starts from buys at; the search may move it."""

    sell_score: Score[int]


@dataclass(
    frozen=True, kw_only=True, config=ConfigDict(json_schema_serialization_defaults_required=True, use_attribute_docstrings=True)
)
class BacktestTrade:
    """
    One position of a backtest from its first BUY to its SELL, or to the backtest's last session when it is still held
    then. Later BUYs of a held stock add to the same trade. Every field is in every answer, so the Web API's schema
    requires each one.
    """

    stock_id: NonEmptyText
    stock_name: str | None = None
    quantity: PositiveInt
    bought_on: date
    """The session of the first BUY."""

    average_cost: PositiveFiniteFloat
    """Per share, the buy fees included, as Position.average_cost."""

    sold_on: date | None = None
    sold_at: PositiveFiniteFloat | None = None
    """The SELL's fill price. None while the trade is still open at the last session."""

    exit_source: SignalSource | None = None
    """What sold it: the stop-loss or the score. None while the trade is still open at the last session."""

    pnl: FiniteFloat
    """
    Net of every fee and the tax (Position.profit_on_sale). For a trade still open, what selling it at the last
    session's close would bring.
    """

    fee: NonNegativeInt
    """The broker fees paid: every BUY's, and the SELL's once sold."""

    tax: NonNegativeInt
    held_sessions: NonNegativeInt
    """Sessions from the first BUY to the SELL, or to the last session."""

    @model_validator(mode="after")
    def _a_sale_has_its_session_price_and_source(self) -> Self:
        if len({self.sold_on is None, self.sold_at is None, self.exit_source is None}) != 1:
            raise ValueError("a sold trade has sold_on, sold_at and exit_source, and an open one has none of them")

        return self

    @computed_field
    @property
    def return_pct(self) -> float:
        """The PnL as a fraction of what the shares cost."""
        return self.pnl / (self.quantity * self.average_cost)


@dataclass(frozen=True, kw_only=True)
class Backtest:
    """
    What one technical strategy would have done over past sessions, replayed day by day with the live trading rules on
    the technical score alone: the inputs it ran with, the account at each session's close, the TAIEX over the same
    sessions and every trade. It placed no order and touched no account.
    """

    backtest_id: BacktestId = Field(default_factory=new_backtest_id)
    created_at: datetime

    strategy_id: FormulaId
    strategy_name: NonEmptyText
    inputs: BacktestInputs
    stop_loss_pct: ProperFraction
    """analysis.stop_loss_pct when it ran."""

    risk_per_trade_pct: Annotated[float, Field(gt=0, le=1)]
    """analysis.risk_per_trade_pct when it ran."""

    equity_curve: Annotated[dict[date, Account], Field(min_length=1)]
    """The account at the close of each session, in session order, its positions marked at that close."""

    benchmark: list[Ohlcv]
    """The TAIEX's daily bars from the first to the last session, oldest first. Empty when the history holds none."""

    trades: list[BacktestTrade]
    """In the order they were sold, then the trades still open at the last session."""

    @property
    def first_session(self) -> date:
        """The first session replayed: the first one on or after inputs.first."""
        return next(iter(self.equity_curve))

    @property
    def last_session(self) -> date:
        return next(reversed(self.equity_curve))

    @property
    def final_equity(self) -> float:
        """Cash plus the open positions at the last session's close, before the costs of selling them."""
        return self.equity_curve[self.last_session].equity

    @property
    def total_return_pct(self) -> float:
        return self.final_equity / self.inputs.initial_cash - 1

    @property
    def benchmark_return_pct(self) -> float | None:
        """The TAIEX's close on the last session over its close on the first. None without both."""
        if len(self.benchmark) < 2:
            return None

        return self.benchmark[-1].close / self.benchmark[0].close - 1

    @property
    def max_drawdown_pct(self) -> float:
        """The deepest fall of the equity from an earlier high, as a fraction of that high."""
        high, deepest = self.inputs.initial_cash, 0.0

        for account in self.equity_curve.values():
            high = max(high, account.equity)
            deepest = max(deepest, 1 - account.equity / high)

        return deepest

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> int:
        """The trades with a PnL above zero, the open ones at the last session's close."""
        return sum(trade.pnl > 0 for trade in self.trades)

    @property
    def fee(self) -> int:
        return sum(trade.fee for trade in self.trades)

    @property
    def tax(self) -> int:
        return sum(trade.tax for trade in self.trades)

    @property
    def average_held_sessions(self) -> float | None:
        """None without a trade."""
        if not self.trades:
            return None

        return sum(trade.held_sessions for trade in self.trades) / len(self.trades)
