from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.trading.exit import ExitRule
from a_domain.types.enums import TradeAction
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class AccountRiskCheck:
    """
    Use Case: Fast account-level risk pre-check.

    This runs after AccountLoader.

    It only checks emergency stop-loss.
    It does not do score-based SELL, ADD, AI analysis, or full-funnel decisions.
    """

    def __init__(
        self,
        price_provider: IOhlcvProvider,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._price_provider = price_provider
        self._exit_rule = ExitRule(
            stop_loss_pct=config.analysis.stop_loss_pct,
            sell_threshold=config.analysis.max_combined_score_sell,
        )
        self._logger = logger

    async def execute(self, status: PipelineStatus) -> None:
        if not status.held_stocks:
            self._logger.info("Account risk check skipped. No held positions.")
            return

        realtime_bars = await self._price_provider.fetch_realtime_bars(status.held_stocks)

        for stock in status.held_stocks:
            position = status.positions_by_stock_id.get(stock.stock_id)

            if position is None:
                continue

            bar = realtime_bars.get(stock.stock_id)

            if bar is None:
                self._logger.warning(f"Risk check skipped. Missing realtime bar: {stock.stock_id}")
                continue

            stock.ohlcv = [bar]

            signal = self._exit_rule.decide_stop_loss_only(
                stock=stock,
                position=position,
            )

            if signal.action != TradeAction.SELL:
                continue

            status.signals.append(signal)
            status.risk_blocked_stock_ids.add(stock.stock_id)

            self._logger.warning(
                f"Emergency stop-loss signal generated: "
                f"{stock.stock_id}, qty={signal.quantity}, "
                f"price={signal.price_at_signal}, "
                f"stop_loss={signal.stop_loss_price}"
            )
