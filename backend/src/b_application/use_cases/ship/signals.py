from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.rules.trading.decision import DecisionRule
from a_domain.rules.trading.entry import EntryRule
from a_domain.rules.trading.exit import ExitRule
from a_domain.rules.trading.sizing import SizingRule
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class Signals:
    """Generates and persists trading signals."""

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

    async def execute(
        self,
        watchlist: StockWatchlist,
        status: PipelineStatus,
    ) -> None:
        self._logger.info(
            f"Generating signals for "
            f"{len(watchlist.willing_stocks)} watchlist stocks."
        )

        generated_signals: list[TradeSignal] = []

        for stock in watchlist.willing_stocks:
            signal = self.generate_signal(stock, status)

            if signal is not None:
                status.signals.append(signal)
                generated_signals.append(signal)

        if not generated_signals:
            self._logger.info("No new trading signals were generated.")
            return

        await self.persist_signals(
            generated_signals,
            status,
        )

    def generate_signal(
        self,
        stock: Stock,
        status: PipelineStatus,
    ) -> TradeSignal | None:
        if stock.stock_id in status.risk_blocked_stock_ids:
            self._logger.warning(
                f"Signal skipped. Risk blocked: {stock.stock_id}"
            )
            return None

        if stock.stock_id in status.stale_stock_ids:
            self._logger.warning(
                f"Signal skipped. Market data is stale: {stock.stock_id}"
            )
            return None

        if stock.composite_score is None:
            self._logger.warning(
                f"Signal skipped. Composite score unavailable: {stock.stock_id}"
            )
            return None

        try:
            return self._decision_rule.decide(
                stock=stock,
                account=status.account,
                position=status.positions_by_stock_id.get(stock.stock_id),
            )

        except Exception as error:
            message = (
                f"Signal generation failed for "
                f"{stock.stock_id}: {error}"
            )
            self._logger.error(message)
            status.stats.add_error(message)
            return None

    async def persist_signals(
        self,
        signals: list[TradeSignal],
        status: PipelineStatus,
    ) -> None:
        try:
            await self._signal_repository.save_batch(signals)
            status.stats.signals_generated += len(signals)

        except Exception as error:
            message = f"Signal persistence failed: {error}"
            self._logger.error(message)
            status.stats.add_error(message)
            return

        self._logger.info(
            f"Signals persisted: total={len(signals)}"
        )
