from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.rules.scoring.composite import CompositeScoreRule
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

    async def execute(self, workflow_state: PipelineContext) -> None:
        stocks = workflow_state.analysed
        self._logger.info(f"Generating signals for {len(stocks)} analyzed stocks...")
        signals: list[TradeSignal] = []

        for stock in stocks:
            stock.combined_score = self._composite_rule.calculate(
                technical_score=stock.technical_score,
                sentiment_score=stock.ai_score,
            )
            stock.stage = AnalysisStage.DECIDED


        signal = self._decision_rule.decide(
            stock=stock,
            account=workflow_state.account,
            position=position,
        )
        if signal:
                signals.append(signal)
                self._logger.info(f"Signal: {signal.action.value} {signal.stock_id} (Qty: {signal.quantity}) | {signal.reason}")

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

        workflow_state.buy_signals = signals
        workflow_state.stats.signals_generated += len(signals)

# TODO: Think a better way. delete this method later
def _find_position(self, workflow_state: PipelineContext, stock_id: str):
    for position in workflow_state.account.positions:
        if position.stock_id == stock_id:
            return position
    return None


"""

你現在 Signals 是 Buy Flow 的最後一步，workflow_state.analysed 
主要是新候選股票，不是完整持倉股票。所以這裡即使支援 position，也只能防止
「持倉股票又被當成 BUY candidate 重複買」。它還不是完整 holding review。
"""