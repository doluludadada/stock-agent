from a_domain.model.trading.backtest import BacktestInputs
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.rules.trading.backtest import BacktestPeriodRule
from b_application.config.app_config import AppConfig


class BacktestOptions:
    """
    What a backtest of `strategy` may be asked for, as the inputs of the longest one at the live settings: the first
    and the last day the held daily history lets it cover (BacktestPeriodRule), the mock account's opening cash, and
    the scores a run buys and sells at. None while the history holds too few sessions for the strategy's history
    window. It reads which sessions the history holds and loads no bar.
    """

    def __init__(self, ohlcv_provider: IOhlcvProvider, config: AppConfig) -> None:
        self._ohlcv_provider = ohlcv_provider
        self._history_days = config.analysis.history_days
        self._period_rule = BacktestPeriodRule()
        self._initial_cash = config.mock_trading.initial_cash
        self._buy_score = config.analysis.min_combined_score_buy
        self._sell_score = config.analysis.max_combined_score_sell

    async def execute(self, strategy: TechnicalStrategy) -> BacktestInputs | None:
        held = await self._ohlcv_provider.held_span()
        period = self._period_rule.apply(*held, self._history_days(strategy.required_bars)) if held else None

        if period is None:
            return None

        return BacktestInputs(
            first=period[0], last=period[1], initial_cash=self._initial_cash, buy_score=self._buy_score, sell_score=self._sell_score
        )
