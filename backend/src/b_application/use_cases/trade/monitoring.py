from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.rules.trading.exit import ExitRule
from b_application.schemas.pipeline_context import PipelineContext


class Monitoring:
    """Use Case: Check current portfolio for exit signals."""

    def __init__(
        self,
        broker_provider: IExecutionProvider,
        market_provider: IPriceProvider,
        stock_provider: IStockProvider,
        exit_rule: ExitRule,
        logger: ILoggingProvider,
    ):
        self._broker = broker_provider
        self._market = market_provider
        self._stock_provider = stock_provider
        self._exit_rule = exit_rule
        self._logger = logger

    async def execute(self, workflow_state: PipelineContext) -> None:
        self._logger.info("Checking portfolio for exit signals...")

        positions = await self._broker.get_positions()
        if not positions:
            return

        stocks_to_check = []
        for pos in positions:
            stock = await self._stock_provider.get_by_id(pos.stock_id)
            if stock:
                stocks_to_check.append(stock)

        if not stocks_to_check:
            return

        signals: list[TradeSignal] = []
        quotes = await self._market.fetch_realtime_bars(stocks_to_check)

        for pos in positions:
            bar = quotes.get(pos.stock_id)
            if not bar:
                continue

            if self._exit_rule.should_stop_loss(
                current_price=bar.close,
                entry_price=pos.average_cost,
            ):
                signal = self._exit_rule.build_stop_loss_signal(
                    stock_id=pos.stock_id,
                    price=bar.close,
                    quantity=pos.quantity,
                )
                signals.append(signal)
                self._logger.warning(f"Stop loss triggered for {pos.stock_id}")

        workflow_state.exit_signals = signals
