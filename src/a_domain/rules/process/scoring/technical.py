from src.a_domain.model.analysis.analysis_context import AnalysisContext


class TechnicalScoreCalculator:
    """
    Calculator: Calculate the Technical Score (0-100) based on indicators and screening results.
    """

    def calculate(self, context: AnalysisContext) -> int:
        base_score = 50

        if context.is_passed:
            base_score += 25
        elif context.technical_failures:
            failed_rule_penalty = min(len(context.technical_failures) * 10, 25)
            base_score -= failed_rule_penalty

        if context.rsi and context.rsi.val_14 is not None and 40 <= context.rsi.val_14 <= 60:
            base_score += 10

        if context.macd and context.macd.line is not None and context.macd.signal is not None:
            if context.macd.line > context.macd.signal:
                base_score += 10

        if context.ma and context.ma.ma_20 is not None:
            base_score += 5

        return max(0, min(100, base_score))
