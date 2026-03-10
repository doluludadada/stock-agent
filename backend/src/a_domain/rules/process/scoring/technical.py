from dataclasses import dataclass

from a_domain.model.market.stock import Stock


@dataclass(frozen=True)
class TechnicalScoreCalculator:
    """
    Config-driven technical score calculator.
    Fields injected by b_application from AppConfig.
    """

    base: int
    pass_bonus: int
    hard_failure_penalty: int
    max_hard_penalty: int
    soft_failure_penalty: int
    max_soft_penalty: int
    rsi_sweet_spot_bonus: int
    rsi_sweet_spot_min: float
    rsi_sweet_spot_max: float
    macd_bullish_bonus: int
    ma_present_bonus: int

    def calculate(self, stock: Stock) -> int:
        score = self.base

        if stock.is_eliminated:
            hard_penalty = min(len(stock.hard_failures) * self.hard_failure_penalty, self.max_hard_penalty)
            score -= hard_penalty
        else:
            score += self.pass_bonus
            soft_penalty = min(len(stock.soft_failures) * self.soft_failure_penalty, self.max_soft_penalty)
            score -= soft_penalty

        if stock.indicators:
            rsi = stock.indicators.rsi
            if rsi and rsi.val_14 is not None:
                if self.rsi_sweet_spot_min <= rsi.val_14 <= self.rsi_sweet_spot_max:
                    score += self.rsi_sweet_spot_bonus

            macd = stock.indicators.macd
            if macd and macd.line is not None and macd.signal is not None:
                if macd.line > macd.signal:
                    score += self.macd_bullish_bonus

            ma = stock.indicators.ma
            if ma and ma.ma_20 is not None:
                score += self.ma_present_bonus

        return max(0, min(100, score))


