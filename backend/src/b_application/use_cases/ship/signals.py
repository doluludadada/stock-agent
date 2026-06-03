# backend/src/b_application/use_cases/ship/signals.py

from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.rules.scoring.composite import CompositeScoreRule
from a_domain.rules.trading import DecisionRule
from a_domain.types.enums import AnalysisStage, TradeAction
from b_application.schemas.pipeline_context import PipelineContext


class Signals:
    """
    Use Case: Generate and persist final trade decisions.
        - This use case converts analysed stocks into explicit BUY / SELL / HOLD TradeSignal records.
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

    async def execute(self, context: PipelineContext) -> None:
        # Only analysed stocks should receive final combined score and decision.
        stocks = context.analysed

        self._logger.info(f"Generating signals for {len(stocks)} analysed stocks.")

        signals: list[TradeSignal] = []

        for stock in stocks:
            try:
                stock.combined_score = self._composite_rule.calculate(stock)
                stock.stage = AnalysisStage.DECIDED

                # Existing position means the decision must use ExitRule.
                # Missing position means the decision must use EntryRule.
                position = context.positions_by_stock_id.get(stock.stock_id)

                signal = self._decision_rule.decide(
                    stock=stock,
                    account=context.account,
                    position=position,
                )

                signals.append(signal)

                self._logger.info(f"Signal: {signal.action.value} {signal.stock_id} (Qty: {signal.quantity}) | {signal.reason}")

            except Exception as e:
                error_message = f"Signal decision failed for {stock.stock_id}: {e}"
                self._logger.error(error_message)
                context.stats.add_error(error_message)

        if signals:
            try:
                await self._signal_repo.save_batch(signals)
            except Exception as e:
                self._logger.error(f"Failed to persist signals: {e}")
                context.stats.add_error(f"Failed to persist signals: {e}")

        for stock in stocks:
            try:
                await self._knowledge.save_analysis(stock)
            except Exception as e:
                self._logger.error(f"RAG write failed for {stock.stock_id}: {e}")
                context.stats.add_error(f"RAG write failed for {stock.stock_id}: {e}")

        context.buy_signals = [signal for signal in signals if signal.action == TradeAction.BUY]
        context.exit_signals = [signal for signal in signals if signal.action == TradeAction.SELL]
        context.hold_signals = [signal for signal in signals if signal.action == TradeAction.HOLD]
        context.stats.signals_generated += len(signals)

        self._logger.info(
            f"Signals generated: total={len(signals)}, "
            f"buy={len(context.buy_signals)}, "
            f"sell={len(context.exit_signals)}, "
            f"hold={len(context.hold_signals)}"
        )
