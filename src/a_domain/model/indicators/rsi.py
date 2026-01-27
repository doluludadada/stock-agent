from dataclasses import dataclass

@dataclass(frozen=True)
class Rsi:
    """
    Relative Strength Index (RSI) Domain Model.
    """
    val_14: float | None
