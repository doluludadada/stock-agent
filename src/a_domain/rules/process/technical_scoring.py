from src.a_domain.model.analysis.screening_result import ScreeningResult
from src.a_domain.model.analysis.technical_indicators import TechnicalIndicators


class TechnicalScoringRule:
    """
    Rule: Calculate the Technical Score (0-100) based on indicators and screening results.
    """

    def calculate(self, indicators: TechnicalIndicators, screening_result: ScreeningResult) -> int:
        base_score = 50

        if screening_result.passed:
            base_score += 25
        else:
            failed_rule_penalty = min(len(screening_result.failed_rules) * 10, 25)
            base_score -= failed_rule_penalty

        if indicators.rsi_14 is not None and 40 <= indicators.rsi_14 <= 60:
            base_score += 10

        if indicators.macd_line is not None and indicators.macd_signal is not None:
            if indicators.macd_line > indicators.macd_signal:
                base_score += 10

        if indicators.ma_20 is not None:
            base_score += 5

        return max(0, min(100, base_score))
