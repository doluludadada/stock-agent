from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.rules.scoring.composite import CompositeScoreRule
from a_domain.rules.trading.decision import DecisionRule
from a_domain.rules.trading.entry import EntryRule
from a_domain.rules.trading.exit import ExitRule
from a_domain.rules.trading.sizing import SizingRule
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class Signals:
    """
    Generates and persists trading signals.
    """

    def __init__(
        self,
        signal_repository: ISignalRepository,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._signal_repository = signal_repository
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

    async def execute(
        self,
        watchlist: StockWatchlist,
        status: PipelineStatus,
    ) -> None:
        self._logger.info(f"Generating signals for {len(watchlist.willing_stocks)} watchlist stocks.")

        for stock in watchlist.willing_stocks:
            try:
                if stock.stock_id in status.risk_blocked_stock_ids:
                    self._logger.warning(f"Signal skipped. Risk blocked: {stock.stock_id}")
                    continue

                if stock.technical_score is None or stock.ai_score is None:
                    self._logger.warning(f"Signal skipped. Incomplete analysis: {stock.stock_id}")
                    continue

                stock.combined_score = self._composite_rule.calculate(technical_score=stock.technical_score, ai_score=stock.ai_score)

                signal = self._decision_rule.decide(
                    stock=stock, account=status.account, position=status.positions_by_stock_id.get(stock.stock_id)
                )

                status.signals.append(signal)

            except Exception as error:
                message = f"Signal generation failed for {stock.stock_id}: {error}"
                self._logger.error(message)
                status.stats.add_error(message)

        if not status.signals:
            self._logger.info("No trading signals were generated.")
            return

        try:
            await self._signal_repository.save_batch(status.signals)
            status.stats.signals_generated += len(status.signals)

        except Exception as error:
            message = f"Signal persistence failed: {error}"
            self._logger.error(message)
            status.stats.add_error(message)
            return

        self._logger.info(f"Signals persisted: total={len(status.signals)}")
