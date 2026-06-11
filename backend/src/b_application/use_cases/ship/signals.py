from icontract import require

from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import StockWatchlist
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


# TODO: needa clean here
class Signals:
    """
    Generates and persists trading signals from the current runtime watchlist.

    The watchlist contains stocks that already passed technical and AI gates.
    Signal generation decides whether to BUY, SELL, or HOLD now.
    """

    def __init__(
        self,
        signal_repository: ISignalRepository,
        knowledge_repository: IKnowledgeRepository,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._signal_repository = signal_repository
        self._knowledge_repository = knowledge_repository
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
        lambda watchlist, context: len(watchlist.willing_stocks) > 0 or len(context.emergency_exit_signals) > 0,
        "Signal generation requires watchlist stocks or emergency exits",
    )
    async def execute(
        self,
        watchlist: StockWatchlist,
        context: PipelineContext,
    ) -> None:
        context.buy_signals.clear()
        context.exit_signals.clear()
        context.hold_signals.clear()

        signals: list[TradeSignal] = [
            *context.emergency_exit_signals,
        ]

        for stock in watchlist.willing_stocks:
            if stock.stock_id in context.risk_blocked_stock_ids:
                self._logger.warning(f"Signal skipped. Risk blocked: {stock.stock_id}")
                continue

            if stock.technical_score is None or stock.ai_score is None:
                self._logger.warning(f"Signal skipped. Incomplete analysis: {stock.stock_id}")
                continue

            try:
                stock.combined_score = self._composite_rule.calculate(
                    technical_score=stock.technical_score,
                    ai_score=stock.ai_score,
                )

                signal = self._decision_rule.decide(
                    stock=stock,
                    account=context.account,
                    position=context.positions_by_stock_id.get(stock.stock_id),
                )

                signals.append(signal)

            except Exception as error:
                error_message = f"Signal generation failed for {stock.stock_id}: {error}"
                self._logger.error(error_message)
                context.stats.add_error(error_message)

        if not signals:
            self._logger.info("No trading signals were generated.")
            return

        try:
            await self._signal_repository.save_batch(signals)
        except Exception as error:
            error_message = f"Signal persistence failed: {error}"
            self._logger.error(error_message)
            context.stats.add_error(error_message)
            return

        context.buy_signals = [signal for signal in signals if signal.action == TradeAction.BUY]
        context.exit_signals = [signal for signal in signals if signal.action == TradeAction.SELL]
        context.hold_signals = [signal for signal in signals if signal.action == TradeAction.HOLD]

        context.stats.signals_generated += len(signals)

        stocks_by_id: dict[str, Stock] = {
            stock.stock_id: stock
            for stock in [
                *context.held_stocks,
                *context.universe_stocks,
                *context.buzz_stocks,
                *context.manual_stocks,
                *watchlist.willing_stocks,
            ]
        }

        for signal in signals:
            stock = stocks_by_id.get(signal.stock_id)

            if stock is None:
                self._logger.warning(f"RAG decision skipped. Stock context not found: {signal.stock_id}")
                continue

            try:
                await self._knowledge_repository.save_decision(
                    stock=stock,
                    signal=signal,
                )
            except Exception as error:
                error_message = f"RAG decision persistence failed for {signal.stock_id}: {error}"
                self._logger.error(error_message)
                context.stats.add_error(error_message)

        self._logger.info(
            f"Signals persisted: total={len(signals)}, "
            f"emergency={len(context.emergency_exit_signals)}, "
            f"buy={len(context.buy_signals)}, "
            f"sell={len(context.exit_signals)}, "
            f"hold={len(context.hold_signals)}"
        )
