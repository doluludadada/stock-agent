# backend/src/b_application/use_cases/ship/signals.py

from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.rules.scoring.composite import CompositeScoreRule
from a_domain.rules.trading.decision import DecisionRule
from a_domain.types.enums import TradeAction
from b_application.schemas.pipeline_context import PipelineContext


class Signals:
    """
    Use Case: Generate final trade signals.

    AccountRiskCheck may produce stop-loss SELL signals before the full funnel.
    This use case owns final signal classification:
    - buy_signals
    - exit_signals
    - hold_signals
    """

    def __init__(
        self,
        decision_rule: DecisionRule,
        composite_rule: CompositeScoreRule,
        signal_repository: ISignalRepository,
        knowledge_repository: IKnowledgeRepository,
        logger: ILoggingProvider,
    ):
        self._decision_rule = decision_rule
        self._composite_rule = composite_rule
        self._signal_repository = signal_repository
        self._knowledge = knowledge_repository
        self._logger = logger

    async def execute(self, context: PipelineContext) -> None:
        stocks = context.survivors
        full_funnel_signals: list[TradeSignal] = []

        for stock in stocks:
            try:
                stock.combined_score = self._composite_rule.calculate(stock)

                position = context.positions_by_stock_id.get(stock.stock_id)

                signal = self._decision_rule.decide(
                    stock=stock,
                    account=context.account,
                    position=position,
                )

                full_funnel_signals.append(signal)

            except Exception as e:
                error_message = f"Signal generation failed for {stock.stock_id}: {e}"
                self._logger.error(error_message)
                context.stats.add_error(error_message)

        all_signals = [
            *context.emergency_exit_signals,
            *full_funnel_signals,
        ]

        if all_signals:
            try:
                await self._signal_repository.save_batch(all_signals)
            except Exception as e:
                error_message = f"Failed to persist signals: {e}"
                self._logger.error(error_message)
                context.stats.add_error(error_message)

        for stock in stocks:
            try:
                await self._knowledge.save_analysis(stock)
            except Exception as e:
                error_message = f"RAG write failed for {stock.stock_id}: {e}"
                self._logger.error(error_message)
                context.stats.add_error(error_message)

        context.buy_signals = [signal for signal in all_signals if signal.action == TradeAction.BUY]
        context.exit_signals = [signal for signal in all_signals if signal.action == TradeAction.SELL]
        context.hold_signals = [signal for signal in all_signals if signal.action == TradeAction.HOLD]

        context.stats.signals_generated += len(all_signals)

        self._logger.info(
            f"Signals generated: total={len(all_signals)}, "
            f"account_risk_exit={len(context.emergency_exit_signals)}, "
            f"full_funnel={len(full_funnel_signals)}, "
            f"buy={len(context.buy_signals)}, "
            f"sell={len(context.exit_signals)}, "
            f"hold={len(context.hold_signals)}"
        )
