"""
Use Case: Filter candidates through technical analysis.

The funnel gatekeeper - only survivors pass to the next stage.
"""
from backend.src.a_domain.model.analysis.analysis_context import AnalysisContext
from backend.src.a_domain.ports.analysis.technical_analysis_provider import ITechnicalAnalysisProvider
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy
from backend.src.a_domain.rules.process.scoring.technical import TechnicalScoreCalculator
from backend.src.a_domain.types.enums import AnalysisStage


class FilterCandidates:
    """
    The Funnel Gatekeeper.
    
    Applies technical analysis and only allows qualified stocks to proceed.
    This prevents wasting AI API calls on stocks that don't pass basic criteria.
    """

    def __init__(
        self,
        tech_provider: ITechnicalAnalysisProvider,
        screening_policy: TechnicalScreeningPolicy,
        score_calculator: TechnicalScoreCalculator,
        logger: ILoggingProvider,
    ):
        self._tech_provider = tech_provider
        self._policy = screening_policy
        self._calculator = score_calculator
        self._logger = logger

    def execute(
        self,
        contexts: list[AnalysisContext],
        is_intraday: bool = True,
    ) -> list[AnalysisContext]:
        self._logger.info(f"Filtering {len(contexts)} candidates (intraday={is_intraday})...")
        survivors: list[AnalysisContext] = []

        for ctx in contexts:
            # Data integrity check
            if not ctx.ohlcv_data or ctx.current_price is None:
                ctx.stage = AnalysisStage.FILTERED_FAIL
                continue

            try:
                # 1. Calculate technical indicators (One call)
                ctx.indicators = self._tech_provider.calculate_indicators(ctx.ohlcv_data)

                # 2. Evaluate rules
                failed_rules = self._policy.evaluate(ctx, is_intraday=is_intraday)
                ctx.technical_failures = failed_rules

                # 3. Calculate technical score
                ctx.technical_score = self._calculator.calculate(ctx)

                # 4. Funnel decision (Logic moved here from Context)
                if not failed_rules:
                    ctx.stage = AnalysisStage.FILTERED_PASS
                    survivors.append(ctx)
                else:
                    ctx.stage = AnalysisStage.FILTERED_FAIL
                    self._logger.debug(f"Drop {ctx.stock.stock_id}: Failed {failed_rules}")

            except Exception as e:
                self._logger.error(f"Error filtering {ctx.stock.stock_id}: {e}")
                ctx.stage = AnalysisStage.FILTERED_FAIL

        return survivors


