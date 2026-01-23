from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.ports.analysis.technical_analysis_port import ITechnicalAnalysisPort
from src.a_domain.ports.system.logging_port import ILoggingPort
from src.a_domain.rules.process.technical_scoring import TechnicalScoringRule
from src.a_domain.rules.process.technical_screening import TechnicalScreeningPolicy


class TechnicalAnalyser:
    """
    Use Case: Orchestrate Technical Analysis.
    Flow: Infra(Calc) -> Domain(Screening) -> Domain(Scoring)
    """

    def __init__(
        self,
        tech_port: ITechnicalAnalysisPort,
        screening_policy: TechnicalScreeningPolicy,
        scoring_rule: TechnicalScoringRule,
        logger: ILoggingPort,
    ):
        self._tech_port = tech_port
        self._screening_policy = screening_policy
        self._scoring_rule = scoring_rule
        self._logger = logger

    def execute(self, contexts: list[AnalysisContext]) -> list[AnalysisContext]:
        self._logger.info(f"Running technical analysis on {len(contexts)} stocks")
        passed_count = 0

        for ctx in contexts:
            if not ctx.ohlcv_data or ctx.current_price is None:
                self._logger.warning(
                    f"Skipping {ctx.stock.stock_id}: missing price data"
                )
                continue

            try:
                # 1. Calculate Indicators (Infra Port)
                indicators = self._tech_port.calculate_indicators(ctx.ohlcv_data)
                ctx.indicators = indicators

                # 2. Apply Screening Policy (Domain Rule)
                screening_result = self._screening_policy.evaluate(
                    indicators=indicators,
                    current_price=ctx.current_price,
                )
                ctx.screening_result = screening_result

                # 3. Calculate Technical Score (Domain Rule)
                ctx.technical_score = self._scoring_rule.calculate(
                    indicators, screening_result
                )

                if screening_result.passed:
                    passed_count += 1

            except Exception as e:
                self._logger.error(
                    f"Technical analysis failed for {ctx.stock.stock_id}: {e}"
                )
                ctx.technical_score = 0

        self._logger.success(
            f"Technical analysis complete. {passed_count}/{len(contexts)} passed screening"
        )
        return contexts
