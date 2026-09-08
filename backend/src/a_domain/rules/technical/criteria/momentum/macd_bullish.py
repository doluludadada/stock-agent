# backend/src/a_domain/rules/technical/criteria/momentum/macd_bullish.py

from dataclasses import dataclass

from a_domain.model.market.stock import Stock


@dataclass(frozen=True)
class MacdBullishCriterion:
    # TODO: Check this file
    """Checks the current bullish MACD state."""

    require_above_signal: bool = True
    require_positive: bool = False
    require_histogram_positive: bool = False

    @property
    def name(self) -> str:
        checks: list[str] = []

        if self.require_above_signal:
            checks.append("line > signal")

        if self.require_positive:
            checks.append("line > 0")

        if self.require_histogram_positive:
            checks.append("histogram > 0")

        if not checks:
            return "MACD Available"

        return f"MACD Bullish ({', '.join(checks)})"

    def apply(self, stock: Stock) -> bool:
        macd = stock.indicators.macd

        if macd is None:
            return False

        if self.require_above_signal and macd.line <= macd.signal:
            return False

        if self.require_positive and macd.line <= 0:
            return False

        return not self.require_histogram_positive or macd.histogram > 0
