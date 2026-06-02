from dataclasses import dataclass

from a_domain.model.market.stock import Stock


@dataclass(frozen=True)
class TechnicalScoreCalculator:
    """
    Config-driven Technical Score Calculator.

    Iterates over technical screening failures and applies configuration-driven
    penalties or positive indicator sweet-spot bonuses to output a raw technical score.
    """

    base: int
    """
    Starting baseline technical score.
    """

    pass_bonus: int
    """
    Bonus points awarded if the stock incurs no hard failures.
    """

    hard_failure_penalty: int
    """
    Points deducted per active hard failure.
    """

    max_hard_penalty: int
    """
    Ceiling limit on cumulative hard failure deductions.
    """

    soft_failure_penalty: int
    """
    Points deducted per active soft (should_pass) failure.
    """

    max_soft_penalty: int
    """
    Ceiling limit on cumulative soft failure deductions.
    """

    rsi_sweet_spot_bonus: int
    """
    Bonus points if RSI lies in a healthy accumulation range.
    """

    rsi_sweet_spot_min: float
    """
    Lower bound of the RSI sweet-spot.
    """

    rsi_sweet_spot_max: float
    """
    Upper bound of the RSI sweet-spot.
    """

    macd_bullish_bonus: int
    """
    Bonus points if MACD is in a bullish configuration.
    """

    ma_present_bonus: int
    """
    Bonus points if a valid trend MA reference is present.
    """

    def calculate(self, stock: Stock) -> int:
        """Computes the overall technical score for the stock."""
        score = self.base

        if stock.is_eliminated:
            hard_penalty = min(
                len(stock.hard_failures) * self.hard_failure_penalty,
                self.max_hard_penalty,
            )
            score -= hard_penalty
        else:
            score += self.pass_bonus

            soft_penalty = min(
                len(stock.soft_failures) * self.soft_failure_penalty,
                self.max_soft_penalty,
            )
            score -= soft_penalty

        score += self._indicator_bonus(stock)

        return self._clamp(score)

    def _indicator_bonus(self, stock: Stock) -> int:
        if stock.indicators is None:
            return 0

        bonus = 0

        rsi = stock.indicators.rsi
        if rsi is not None and rsi.val_14 is not None:
            if self.rsi_sweet_spot_min <= rsi.val_14 <= self.rsi_sweet_spot_max:
                bonus += self.rsi_sweet_spot_bonus

        macd = stock.indicators.macd
        if macd is not None and macd.line is not None and macd.signal is not None:
            if macd.line > macd.signal:
                bonus += self.macd_bullish_bonus

        ma = stock.indicators.ma
        if ma is not None and ma.ma_20 is not None:
            bonus += self.ma_present_bonus

        return bonus

    def _clamp(self, score: int) -> int:
        return max(0, min(100, score))