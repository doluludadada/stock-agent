from src.a_domain.model.analysis.analysis_context import AnalysisContext


class TechnicalScoreCalculator:
    """
    Technical Score Calculator: Computes a 0-100 score based on technical indicators.
    """

    def calculate(self, context: AnalysisContext) -> int:
        base_score = 50

        # Check failures directly
        if not context.technical_failures:
            base_score += 25
        else:
            failed_rule_penalty = min(len(context.technical_failures) * 10, 25)
            base_score -= failed_rule_penalty

        # Access via indicators aggregate
        if context.indicators:
            # RSI Bonus
            rsi = context.indicators.rsi
            if rsi and rsi.val_14 is not None and 40 <= rsi.val_14 <= 60:
                base_score += 10

            # MACD Bonus
            macd = context.indicators.macd
            if macd and macd.line is not None and macd.signal is not None:
                if macd.line > macd.signal:
                    base_score += 10

            # MA Bonus
            ma = context.indicators.ma
            if ma and ma.ma_20 is not None:
                base_score += 5

        return max(0, min(100, base_score))
