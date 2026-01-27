from dataclasses import dataclass


@dataclass(frozen=True)
class Macd:
    """
    Moving Average Convergence Divergence (MACD) Domain Model.
    """
    line: float | None
    signal: float | None
