from dataclasses import dataclass

from a_domain.model.market.stock import Stock


@dataclass(frozen=True)
class MacdBullishCriterion:
    """
    MACD bullish condition.

    The factory decides which checks are required for each strategy.
    """

    require_cross: bool = True
    require_positive: bool = False
    require_histogram_positive: bool = False
    allow_missing: bool = False

    @property
    def name(self) -> str:
        checks: list[str] = []

        if self.require_cross:
            checks.append("cross")

        if self.require_positive:
            checks.append("positive")

        if self.require_histogram_positive:
            checks.append("histogram")

        if not checks:
            return "MACD Available"

        return f"MACD Bullish ({', '.join(checks)})"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.macd is None:
            return self.allow_missing

        macd = stock.indicators.macd

        if self.require_cross:
            if macd.line is None or macd.signal is None:
                return self.allow_missing

            if macd.line <= macd.signal:
                return False

        if self.require_positive:
            if macd.line is None:
                return self.allow_missing

            if macd.line <= 0:
                return False

        if self.require_histogram_positive:
            if macd.histogram is None:
                return self.allow_missing

            if macd.histogram <= 0:
                return False

        return True
