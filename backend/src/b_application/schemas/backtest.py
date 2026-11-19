from dataclasses import dataclass

from a_domain.model.trading.backtest import BacktestInputs
from a_domain.rules.technical.strategy import TechnicalStrategy


@dataclass(frozen=True)
class BacktestSetup:
    """What the backtest page offers before a backtest runs, as Pipeline.load_backtest_options returns it."""

    strategy: TechnicalStrategy
    """StrategyLoader: the strategy a backtest would replay, the owner's active one or a built-in one."""

    inputs: BacktestInputs | None
    """
    BacktestOptions: the inputs of the longest backtest the held daily history allows at the live settings; None while
    it allows none.
    """
