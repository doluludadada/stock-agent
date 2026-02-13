from backend.src.a_domain.model.trading.signal import TradeSignal
from backend.src.a_domain.ports.market.market_provider import IMarketProvider
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.ports.trading.broker_provider import IBrokerProvider
from backend.src.a_domain.rules.trading.exit import ExitRule
from backend.src.a_domain.types.constants import REASON_STOP_LOSS
from backend.src.a_domain.types.enums import SignalAction, SignalSource


class Monitoring:
    """
    Trade: Checks current portfolio for exit signals (Stop Loss/Take Profit).
    """

    def __init__(
        self,
        broker_provider: IBrokerProvider,
        market_provider: IMarketProvider,
        logger: ILoggingProvider,
        stop_loss_pct: float = 0.10,
    ):
        self._broker = broker_provider
        self._market = market_provider
        self._logger = logger
        self._stop_loss_pct = stop_loss_pct

    async def execute(self) -> list[TradeSignal]:
        self._logger.info("Checking portfolio for exit signals...")

        positions = await self._broker.get_positions()
        if not positions:
            return []

        signals = []
        stock_ids = [p.stock_id for p in positions]
        quotes = await self._market.fetch_realtime_bars(stock_ids)

        for pos in positions:
            bar = quotes.get(pos.stock_id)
            if not bar:
                continue

            # Check Stop Loss
            if ExitRule.should_stop_loss(
                current_price=bar.close_price, entry_price=pos.average_cost, threshold_pct=self._stop_loss_pct
            ):
                signal = TradeSignal(
                    stock_id=pos.stock_id,
                    action=SignalAction.SELL,
                    price_at_signal=bar.close_price,
                    source=SignalSource.TECHNICAL,
                    score=0,
                    reason=REASON_STOP_LOSS,  # Using Constant
                    quantity=pos.quantity,
                )
                signals.append(signal)
                self._logger.warning(f"Stop loss triggered for {pos.stock_id}")

        return signals


