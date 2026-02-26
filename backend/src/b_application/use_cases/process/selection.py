"""
Use Case: Filter candidates through technical analysis.

The funnel gatekeeper — only survivors pass to the next stage.
"""
from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy
from backend.src.a_domain.rules.process.scoring.technical import TechnicalScoreCalculator
from backend.src.a_domain.types.enums import AnalysisStage


class Selection:
    """
    The Funnel Gatekeeper.

    Applies technical analysis and only allows qualified stocks to proceed.
    Prevents wasting AI API calls on stocks that don't pass basic criteria.
    """

    def __init__(
        self,
        tech_provider: IIndicatorProvider,
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
        candidates: list[Stock],
        is_intraday: bool = True,
    ) -> list[Stock]:
        self._logger.info(f"Filtering {len(candidates)} candidates (intraday={is_intraday})...")
        survivors: list[Stock] = []

        for candidate in candidates:
            if not candidate.ohlcv or candidate.current_price is None:
                candidate.stage = AnalysisStage.FILTERED_FAIL
                continue

            try:
                # 1. Calculate technical indicators
                candidate.indicators = self._tech_provider.calculate_indicators(candidate.ohlcv)

                # 2. Evaluate rules
                self._policy.evaluate(candidate, is_intraday=is_intraday)

                # 3. Calculate technical score
                candidate.technical_score = self._calculator.calculate(candidate)

                # 4. Funnel decision
                if not candidate.is_eliminated:
                    candidate.stage = AnalysisStage.FILTERED_PASS
                    survivors.append(candidate)
                else:
                    candidate.stage = AnalysisStage.FILTERED_FAIL
                    self._logger.debug(
                        f"Drop {candidate.stock_id}: Failed {candidate.hard_failures}"
                    )

            except Exception as e:
                self._logger.error(f"Error filtering {candidate.stock_id}: {e}")
                candidate.stage = AnalysisStage.FILTERED_FAIL

        self._logger.info(f"Survivors: {len(survivors)}/{len(candidates)}")
        return survivors
