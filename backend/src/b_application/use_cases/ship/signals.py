# backend/src/b_application/use_cases/ship/signals.py
from icontract import require

from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.rules.scoring.composite import CompositeScoreRule
from a_domain.rules.trading.decision import DecisionRule
from a_domain.rules.trading.entry import EntryRule
from a_domain.rules.trading.exit import ExitRule
from a_domain.rules.trading.sizing import SizingRule
from a_domain.types.enums import TradeAction
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class Signals:
    """
    Use Case: Generate final trade signals.

    Responsibilities:
    - calculate combined score
    - generate BUY / SELL / HOLD signals
    - merge emergency exit signals
    - persist generated signals
    - persist RAG analysis memory
    - persist RAG decision memory
    """

    def __init__(
        self,
        signal_repository: ISignalRepository,
        knowledge_repository: IKnowledgeRepository,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._signal_repository = signal_repository
        self._knowledge = knowledge_repository
        self._logger = logger

        sizing_rule = SizingRule(
            risk_per_trade_pct=config.analysis.risk_per_trade_pct,
            stop_loss_pct=config.analysis.stop_loss_pct,
            lot_size=1,
        )

        self._decision_rule = DecisionRule(
            entry_rule=EntryRule(
                buy_threshold=config.analysis.min_combined_score_buy,
                sizing_rule=sizing_rule,
            ),
            exit_rule=ExitRule(
                stop_loss_pct=config.analysis.stop_loss_pct,
                sell_threshold=config.analysis.max_combined_score_sell,
            ),
        )

        self._composite_rule = CompositeScoreRule(
            technical_weight=config.analysis.technical_weight,
            sentiment_weight=config.analysis.sentiment_weight,
        )

    @require(
        lambda context: len(context.survivors) > 0 or len(context.emergency_exit_signals) > 0,
        "Must have stocks to analyze or emergency exits to process",
    )
    async def execute(self, context: PipelineContext) -> None:
        stocks = context.survivors
        full_funnel_signals: list[TradeSignal] = []

        for stock in stocks:
            try:
                stock.combined_score = self._composite_rule.calculate(stock)

                signal = self._decision_rule.decide(
                    stock=stock,
                    account=context.account,
                    position=context.positions_by_stock_id.get(stock.stock_id),
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

        stocks_by_id: dict[str, Stock] = {
            stock.stock_id: stock
            for stock in [
                *context.held_candidates,
                *stocks,
            ]
        }

        for stock in stocks:
            try:
                await self._knowledge.save_analysis(stock)
            except Exception as e:
                error_message = f"RAG analysis write failed for {stock.stock_id}: {e}"
                self._logger.error(error_message)
                context.stats.add_error(error_message)

        for signal in all_signals:
            stock = stocks_by_id.get(signal.stock_id)

            if stock is None:
                self._logger.warning(f"RAG decision write skipped. Stock not found: {signal.stock_id}")
                continue

            try:
                await self._knowledge.save_decision(stock, signal)
            except Exception as e:
                error_message = f"RAG decision write failed for {signal.stock_id}: {e}"
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
