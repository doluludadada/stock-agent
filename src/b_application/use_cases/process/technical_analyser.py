from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.ports.analysis.technical_analysis_provider import ITechnicalAnalysisProvider
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.a_domain.rules.process.scoring.technical import TechnicalScoreCalculator
from src.a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy


class TechnicalAnalyser:
    """
    Use Case: Orchestrate Technical Analysis.
    Flow: Infra(Calc) -> Domain(Screening) -> Domain(Scoring)
    """

    def __init__(
        self,
        tech_port: ITechnicalAnalysisProvider,
        screening_policy: TechnicalScreeningPolicy,
        scoring_calculator: TechnicalScoreCalculator,
        logger: ILoggingProvider,
    ):
        self._tech_port = tech_port
        self._screening_policy = screening_policy
        self._scoring_calculator = scoring_calculator
        self._logger = logger

    def execute(self, contexts: list[AnalysisContext]) -> list[AnalysisContext]:
        self._logger.info(f"Running technical analysis on {len(contexts)} stocks")
        passed_count = 0

        for ctx in contexts:
            if not ctx.ohlcv_data or ctx.current_price is None:
                ctx.technical_failures.append("Missing Data")
                continue

            try:
                # 1. Calculate Indicators (Infra Port)
                # 直接填入 Context
                ctx.rsi, ctx.macd, ctx.ma = self._tech_port.calculate_indicators(ctx.ohlcv_data)

                # 2. Apply Screening (Domain Rule)
                failed_reasons = self._screening_policy.evaluate(ctx)
                ctx.technical_failures = failed_reasons

                # 3. Calculate Score (Domain Rule)
                ctx.technical_score = self._scoring_calculator.calculate(ctx)

                if ctx.is_passed:
                    passed_count += 1

            except Exception as e:
                self._logger.error(f"Technical analysis failed for {ctx.stock.stock_id}: {e}")
                ctx.technical_failures.append(f"Exception: {str(e)}")
                ctx.technical_score = 0

        self._logger.success(f"Technical analysis complete. {passed_count}/{len(contexts)} passed.")
        return contexts
