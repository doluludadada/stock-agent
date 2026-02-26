from backend.src.a_domain.model.market.stock import Stock


class TechnicalScoreCalculator:
    """
    Computes a 0-100 technical score based on rule evaluation results.

    Scoring logic:
    - Start at base_score
    - If eliminated (hard failure): apply hard penalty
    - If survived: apply pass bonus, then soft penalty per soft failure
    - Indicator bonuses for strong signals
    """

    def __init__(
        self,
        base_score: int = 50,
        pass_bonus: int = 20,
        hard_failure_penalty: int = 15,
        max_hard_penalty: int = 30,
        soft_failure_penalty: int = 5,
        max_soft_penalty: int = 15,
        rsi_sweet_spot_bonus: int = 10,
        rsi_sweet_spot_min: float = 40.0,
        rsi_sweet_spot_max: float = 60.0,
        macd_bullish_bonus: int = 10,
        ma_present_bonus: int = 5,
    ):
        self._base_score = base_score
        self._pass_bonus = pass_bonus
        self._hard_failure_penalty = hard_failure_penalty
        self._max_hard_penalty = max_hard_penalty
        self._soft_failure_penalty = soft_failure_penalty
        self._max_soft_penalty = max_soft_penalty
        self._rsi_sweet_spot_bonus = rsi_sweet_spot_bonus
        self._rsi_sweet_spot_min = rsi_sweet_spot_min
        self._rsi_sweet_spot_max = rsi_sweet_spot_max
        self._macd_bullish_bonus = macd_bullish_bonus
        self._ma_present_bonus = ma_present_bonus

    def calculate(self, stock: Stock) -> int:
        score = self._base_score

        if stock.is_eliminated:
            hard_penalty = min(
                len(stock.hard_failures) * self._hard_failure_penalty,
                self._max_hard_penalty,
            )
            score -= hard_penalty
        else:
            score += self._pass_bonus
            soft_penalty = min(
                len(stock.soft_failures) * self._soft_failure_penalty,
                self._max_soft_penalty,
            )
            score -= soft_penalty

        if stock.indicators:
            rsi = stock.indicators.rsi
            if rsi and rsi.val_14 is not None:
                if self._rsi_sweet_spot_min <= rsi.val_14 <= self._rsi_sweet_spot_max:
                    score += self._rsi_sweet_spot_bonus

            macd = stock.indicators.macd
            if macd and macd.line is not None and macd.signal is not None:
                if macd.line > macd.signal:
                    score += self._macd_bullish_bonus

            ma = stock.indicators.ma
            if ma and ma.ma_20 is not None:
                score += self._ma_present_bonus

        return max(0, min(100, score))
