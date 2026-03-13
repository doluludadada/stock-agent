from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.rules.process.scoring.composite import CompositeScoreRule
from a_domain.rules.trading.decision import DecisionRule
from a_domain.types.enums import AnalysisStage
from b_application.schemas.pipeline_context import PipelineContext


class Signals:
    """
    Use Case: Generate and persist trade signals.
    """

    def __init__(
        self,
        composite_rule: CompositeScoreRule,
        decision_rule: DecisionRule,
        signal_repo: ISignalRepository,
        knowledge_repo: IKnowledgeRepository,
        logger: ILoggingProvider,
    ):
        self._composite_rule = composite_rule
        self._decision_rule = decision_rule
        self._signal_repo = signal_repo
        self._knowledge = knowledge_repo
        self._logger = logger

    async def execute(self, ctx: PipelineContext) -> None:
        stocks = ctx.analysed
        self._logger.info(f"Generating signals for {len(stocks)} analyzed stocks...")
        signals: list[TradeSignal] = []

        for stock in stocks:
            stock.combined_score = self._composite_rule.calculate(
                technical_score=stock.technical_score,
                sentiment_score=stock.ai_score,
            )
            stock.stage = AnalysisStage.DECIDED

            signal = self._decision_rule.decide(stock)
            if signal:
                signals.append(signal)
                self._logger.info(
                    f"Signal: {signal.action} {signal.stock_id} (Score: {signal.score}, Qty: {signal.quantity})"
                )

        if signals:
            try:
                await self._signal_repo.save_batch(signals)
            except Exception as e:
                self._logger.error(f"Failed to persist signals: {e}")

        for stock in stocks:
            try:
                await self._knowledge.save_analysis(stock)
            except Exception as e:
                self._logger.error(f"RAG write failed for {stock.stock_id}: {e}")

        ctx.buy_signals = signals
        ctx.stats.signals_generated += len(signals)
