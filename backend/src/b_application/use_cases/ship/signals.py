"""
Use Case: Generate and persist trade signals.

Converts analyzed candidates into actionable signals.
"""
from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.model.trading.signal import TradeSignal
from backend.src.a_domain.ports.analysis.signal_repository import ISignalRepository
from backend.src.a_domain.ports.chat.knowledge_repository import IKnowledgeRepository
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.rules.process.scoring.composite import CompositeScoreRule
from backend.src.a_domain.rules.trading.decision import DecisionRule
from backend.src.a_domain.types.enums import AnalysisStage


class Signals:
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

    async def execute(self, candidates: list[Stock]) -> list[TradeSignal]:
        self._logger.info(f"Generating signals for {len(candidates)} analyzed stocks...")
        signals: list[TradeSignal] = []

        for candidate in candidates:
            candidate.combined_score = self._composite_rule.calculate(
                technical_score=candidate.technical_score,
                sentiment_score=candidate.sentiment_score,
            )
            candidate.stage = AnalysisStage.DECIDED

            signal = self._decision_rule.decide(candidate)

            if signal:
                signals.append(signal)
                self._logger.info(
                    f"Signal: {signal.action} {signal.stock_id} (Score: {signal.score}, Qty: {signal.quantity})"
                )

        # Persist signals
        if signals:
            try:
                await self._signal_repo.save_batch(signals)
                self._logger.info(f"Persisted {len(signals)} signals")
            except Exception as e:
                self._logger.error(f"Failed to persist signals: {e}")

        # Save to RAG brain
        for candidate in candidates:
            try:
                await self._knowledge.save_analysis(candidate)
            except Exception as e:
                self._logger.error(f"RAG write failed for {candidate.stock_id}: {e}")

        return signals
