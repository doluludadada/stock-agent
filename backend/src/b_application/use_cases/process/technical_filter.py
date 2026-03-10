"""
Use Case: Filter stocks through technical analysis.
The funnel gatekeeper — only survivors pass to the next stage.
"""
from a_domain.model.market.stock import Stock
from a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy
from a_domain.rules.process.scoring.technical import TechnicalScoreCalculator
from a_domain.types.enums import AnalysisStage


class TechnicalFilter:
    """
    The Funnel Gatekeeper.
    Applies technical analysis and only allows qualified stocks to proceed.
    """

    def __init__(
        self,
        tech_provider: IIndicatorProvider,
        screening_policy: TechnicalScreeningPolicy,
        score_calculator: TechnicalScoreCalculator,
        logger: ILoggingProvider,
    ):
        self._tech_provider = tech_provider
        self._policy = screening_policy
        self._calculator = score_calculator
        self._logger = logger

    def execute(self, stocks: list[Stock], is_intraday: bool = True) -> list[Stock]:
        self._logger.info(f"Filtering {len(stocks)} stocks (intraday={is_intraday})...")
        survivors: list[Stock] = []

        for stock in stocks:
            if not stock.ohlcv or stock.current_price is None:
                stock.stage = AnalysisStage.FILTERED_FAIL
                continue

            try:
                stock.indicators = self._tech_provider.calculate_indicators(stock.ohlcv)
                self._policy.evaluate(stock, is_intraday=is_intraday)
                stock.technical_score = self._calculator.calculate(stock)

                if not stock.is_eliminated:
                    stock.stage = AnalysisStage.FILTERED_PASS
                    survivors.append(stock)
                else:
                    stock.stage = AnalysisStage.FILTERED_FAIL
                    self._logger.debug(f"Drop {stock.stock_id}: Failed {stock.hard_failures}")
            except Exception as e:
                self._logger.error(f"Error filtering {stock.stock_id}: {e}")
                stock.stage = AnalysisStage.FILTERED_FAIL

        self._logger.info(f"Survivors: {len(survivors)}/{len(stocks)}")
        return survivors
