from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.ports.system.logging_port import ILoggingPort
from src.a_domain.rules.process.composite_scoring import CompositeScoreRule


class ScoreCombiner:
    """
    Use Case: Apply Composite Scoring Rule.
    """

    def __init__(
        self,
        composite_rule: CompositeScoreRule,
        logger: ILoggingPort,
    ):
        self._composite_rule = composite_rule
        self._logger = logger

    def execute(self, contexts: list[AnalysisContext]) -> list[AnalysisContext]:
        self._logger.info(f"Combining scores for {len(contexts)} stocks")

        for ctx in contexts:
            # Domain Rule Application
            combined = self._composite_rule.calculate(
                technical_score=ctx.technical_score, sentiment_score=ctx.sentiment_score
            )

            ctx.combined_score = combined
            self._logger.trace(f"{ctx.stock.stock_id}: combined={combined}")

        self._logger.success("Score combination complete")
        return contexts
