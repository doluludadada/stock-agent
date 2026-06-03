# backend/src/b_application/use_cases/trade/monitoring.py

from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.trading.exit import ExitRule
from a_domain.types.enums import TradeAction
from b_application.schemas.pipeline_context import PipelineContext


class Monitoring:
    """
    Use Case: Fast emergency exit check.
        - Todo: This class is kept for future EmergencyExitPipeline.
        - It should not run inside the main full-funnel intraday Pipeline.
    """

    def __init__(
        self,
        market_provider: IPriceProvider,
        exit_rule: ExitRule,
        logger: ILoggingProvider,
    ):
        self._market = market_provider
        self._exit_rule = exit_rule
        self._logger = logger


    async def execute(self, context: PipelineContext) -> None:
        self._logger.info("Checking held positions for emergency exits.")

        # Emergency monitoring only applies to already-held positions.
        positions = context.account.positions

        # Held Stock objects are required because ExitRule decides from Stock + Position.
        stocks = context.held_candidates

        if not positions or not stocks:
            return

        # Emergency monitoring uses latest realtime price only.
        quotes = await self._market.fetch_realtime_bars(stocks)

        signals: list[TradeSignal] = []
        # Only emergency SELL signals should be collected here.
        # HOLD signals from emergency monitoring are not useful as alerts.

        for stock in stocks:
            position = context.positions_by_stock_id.get(stock.stock_id)

            if position is None:
                continue

            bar = quotes.get(stock.stock_id)

            if bar is None:
                continue

            stock.ohlcv = [bar]

            signal = self._exit_rule.decide(
                stock=stock,
                position=position,
            )

            if signal.action != TradeAction.SELL:
                continue

            signals.append(signal)
            self._logger.warning(f"Emergency exit triggered for {stock.stock_id}")

        context.exit_signals = signals
