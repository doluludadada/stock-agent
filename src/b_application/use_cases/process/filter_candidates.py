from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.ports.analysis.technical_analysis_provider import ITechnicalAnalysisProvider
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy
from src.a_domain.rules.process.scoring.technical import TechnicalScoreCalculator
from src.a_domain.types.enums import AnalysisStage


class FilterCandidates:
    """
    Use Case: The Funnel Gatekeeper.
    Applies technical analysis on Intraday Data.
    Only allows 'Survivors' to pass to the next stage (AI).
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

    def execute(self, contexts: list[AnalysisContext]) -> list[AnalysisContext]:
        self._logger.info(f"Filtering {len(contexts)} candidates...")
        survivors: list[AnalysisContext] = []

        for ctx in contexts:
            # Data integrity check
            if not ctx.ohlcv_data or ctx.current_price is None:
                self._logger.debug(f"Drop {ctx.stock.stock_id}: Insufficient data.")
                ctx.stage = AnalysisStage.FILTERED_FAIL
                continue

            try:
                # 1. Calculate Indicators (Infra)
                ctx.rsi, ctx.macd, ctx.ma = self._tech_provider.calculate_indicators(ctx.ohlcv_data)

                # 2. Evaluate Rules (Domain Policy)
                failed_rules = self._policy.evaluate(ctx)
                ctx.technical_failures = failed_rules

                # 3. Calculate Tech Score
                ctx.technical_score = self._calculator.calculate(ctx)

                # 4. Funnel Logic
                if not failed_rules:
                    ctx.stage = AnalysisStage.FILTERED_PASS
                    survivors.append(ctx)
                    self._logger.trace(f"Keep {ctx.stock.stock_id}: Passed technicals.")
                else:
                    ctx.stage = AnalysisStage.FILTERED_FAIL
                    self._logger.debug(f"Drop {ctx.stock.stock_id}: Failed rules {failed_rules}")

            except Exception as e:
                self._logger.error(f"Error filtering {ctx.stock.stock_id}: {e}")
                ctx.stage = AnalysisStage.FILTERED_FAIL

        self._logger.success(f"Filter complete. {len(survivors)}/{len(contexts)} survivors.")
        return survivors
