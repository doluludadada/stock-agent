from datetime import UTC, datetime

from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.rules.trading.sizing import SizingRule
from a_domain.types.enums import SignalSource, TradeAction
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.order_execution import OrderExecution


class ManualBuy:
    """
    Use Case: Explicit user BUY override.

    This bypasses the automatic EntryRule BUY threshold.

    It does not bypass:
    - account loading
    - position sizing
    - market-open validation
    - order validation
    - execution-provider validation
    """

    def __init__(
        self,
        account_loader: AccountLoader,
        signal_repository: ISignalRepository,
        order_execution: OrderExecution,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._account_loader = account_loader
        self._signal_repository = signal_repository
        self._order_execution = order_execution
        self._logger = logger

        self._sizing_rule = SizingRule(
            risk_per_trade_pct=config.analysis.risk_per_trade_pct,
            stop_loss_pct=config.analysis.stop_loss_pct,
            lot_size=1,
        )

    async def execute(self, stock: Stock) -> PipelineStatus:
        status = PipelineStatus()
        status.manual_stocks.append(stock)
        status.stocks_cache[stock.stock_id] = stock

        if stock.current_price is None or stock.current_price <= 0:
            status.stats.add_error(f"Manual BUY rejected. Invalid price: {stock.stock_id}")
            status.stats.finish()
            return status

        if stock.composite_score is None:
            status.stats.add_error(f"Manual BUY rejected. Analysis incomplete: {stock.stock_id}")
            status.stats.finish()
            return status

        await self._account_loader.execute(status)

        quantity = self._sizing_rule.calculate(
            account=status.account,
            price=stock.current_price,
        )

        if quantity <= 0:
            status.stats.add_error(f"Manual BUY rejected. No valid quantity: {stock.stock_id}")
            status.stats.finish()
            return status

        signal = TradeSignal(
            stock_id=stock.stock_id,
            action=TradeAction.BUY,
            price_at_signal=stock.current_price,
            source=SignalSource.MANUAL,
            score=stock.composite_score,
            reason="Manual BUY override confirmed by user.",
            quantity=quantity,
            generated_at=datetime.now(UTC),
        )

        await self._signal_repository.save(signal)

        status.signals.append(signal)
        status.stats.signals_generated += 1

        await self._order_execution.execute(
            signals=[signal],
            status=status,
        )

        status.stats.finish()

        self._logger.info(f"Manual BUY completed: {stock.stock_id}, quantity={quantity}, price={stock.current_price}")

        return status
