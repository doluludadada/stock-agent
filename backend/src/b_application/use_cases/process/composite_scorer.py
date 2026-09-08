# backend/src/b_application/use_cases/process/composite_scorer.py

from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.scoring.composite import CompositeScoreRule
from b_application.schemas.config import AppConfig


class CompositeScorer:
    """Calculates the final score from technical and AI analysis."""

    def __init__(
        self,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._score_rule = CompositeScoreRule(
            technical_weight=config.analysis.technical_weight,
            ai_weight=config.analysis.ai_weight,
        )
        self._logger = logger

    def execute(self, stocks: list[Stock]) -> None:
        scored_count = 0

        for stock in stocks:
            stock.composite_score = None

            if stock.technical_score is None or stock.ai_score is None:
                self._logger.warning(f"Composite score skipped. Incomplete analysis: {stock.stock_id}")
                continue

            stock.composite_score = self._score_rule.calculate(
                technical_score=stock.technical_score,
                ai_score=stock.ai_score,
            )
            scored_count += 1

        self._logger.info(f"Composite scoring completed: {scored_count}/{len(stocks)} stocks scored.")
