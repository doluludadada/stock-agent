
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.rules.trading.exit import ExitRule
from a_domain.types.enums import SignalReason, SignalSource, TradeAction
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class Monitoring:
    """
    Use Case: Check current portfolio for exit signals.
    """
    def __init__(
        self,
        broker_provider: IExecutionProvider,
        market_provider: IPriceProvider,
        logger: ILoggingProvider,
        config: AppConfig,
    ):
        self._broker = broker_provider
        self._market = market_provider
        self._logger = logger
        self._config = config

    async def execute(self, ctx: PipelineContext) -> None:
        self._logger.info("Checking portfolio for exit signals...")

        positions = await self._broker.get_positions()
        if not positions:
            return

        signals: list[TradeSignal] = []
        stock_ids = [p.stock_id for p in positions]
        quotes = await self._market.fetch_realtime_bars(stock_ids)

        for pos in positions:
            bar = quotes.get(pos.stock_id)
            if not bar:
                continue
            if ExitRule.should_stop_loss(
                current_price=bar.close,
                entry_price=pos.average_cost,
                threshold_pct=self._config.analysis.stop_loss_pct,
            ):
                # TODO: Should TradeSignal construction be delegated to a factory or builder?
                signal = TradeSignal(
                    stock_id=pos.stock_id,
                    action=TradeAction.SELL,
                    price_at_signal=bar.close,
                    source=SignalSource.TECHNICAL,
                    score=0,
                    reason=SignalReason.STOP_LOSS,
                    quantity=pos.quantity,
                )
                signals.append(signal)
                self._logger.warning(f"Stop loss triggered for {pos.stock_id}")

        ctx.exit_signals = signals
