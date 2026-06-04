from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.trading.exit import ExitRule
from a_domain.types.enums import TradeAction
from b_application.schemas.pipeline_context import PipelineContext


class AccountRiskCheck:
    """
    Use Case: Fast account-level risk pre-check.

    This runs after AccountLoader and before StockSelector.

    It only checks emergency stop-loss.
    It does not do score-based SELL, ADD, AI analysis, or full-funnel decisions.
    """

    def __init__(
        self,
        price_provider: IPriceProvider,
        exit_rule: ExitRule,
        logger: ILoggingProvider,
    ):
        self._price_provider = price_provider
        self._exit_rule = exit_rule
        self._logger = logger

    async def execute(self, context: PipelineContext) -> None:
        if not context.held_candidates:
            self._logger.info("Account risk check skipped. No held positions.")
            return

        realtime_bars = await self._price_provider.fetch_realtime_bars(context.held_candidates)

        for stock in context.held_candidates:
            position = context.positions_by_stock_id.get(stock.stock_id)

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

            context.emergency_exit_signals.append(signal)
            context.risk_blocked_stock_ids.add(stock.stock_id)

            self._logger.warning(
                f"Emergency stop-loss signal generated: "
                f"{stock.stock_id}, qty={signal.quantity}, "
                f"price={signal.price_at_signal}, "
                f"stop_loss={signal.stop_loss_price}"
            )
