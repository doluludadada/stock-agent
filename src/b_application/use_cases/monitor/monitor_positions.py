from src.a_domain.model.trading.signal import TradeSignal
from src.a_domain.ports.market.market_data_provider import IMarketDataProvider
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.a_domain.ports.trading.broker_provider import IBrokerProvider
from src.a_domain.rules.trading.exit import ExitRule
from src.a_domain.types.enums import SignalAction, SignalSource
from src.b_application.schemas.config import AppConfig


class MonitorPositions:
    """
    Use Case: Checks current portfolio against Exit Rules.
    """

    def __init__(
        self,
        broker_provider: IBrokerProvider,
        market_data_provider: IMarketDataProvider,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._broker = broker_provider
        self._market = market_data_provider
        self._config = config
        self._logger = logger

    async def execute(self) -> list[TradeSignal]:
        self._logger.info("Monitoring positions for exit signals...")

        # 1. Get Positions from Broker
        positions = await self._broker.get_positions()
        if not positions:
            return []

        signals = []
        stock_ids = [p.stock_id for p in positions]

        # 2. Get Realtime Price
        quotes = await self._market.fetch_realtime_bars(stock_ids)

        for pos in positions:
            bar = quotes.get(pos.stock_id)
            if not bar:
                continue

            current_price = bar.close_price

            # 3. Apply Domain Rule: ExitRule
            # (Note: Technical exit requires indicators, assuming simple StopLoss for now
            #  to keep this Use Case clean. Full tech exit requires calculating indicators here.)

            should_sell = ExitRule.should_stop_loss(
                current_price=current_price, entry_price=pos.average_cost, threshold_pct=self._config.stop_loss_pct
            )

            if should_sell:
                signal = TradeSignal(
                    stock_id=pos.stock_id,
                    action=SignalAction.SELL,
                    price_at_signal=current_price,
                    source=SignalSource.TECHNICAL,
                    score=0,
                    reason="Stop Loss Triggered",
                    quantity=pos.quantity,
                )
                signals.append(signal)
                self._logger.warning(f"Exit triggered for {pos.stock_id}")

        return signals
