from a_domain.model.market.stock import Stock
from a_domain.rules.technical.calculation.calculator import indicator_series
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.types.enums import IndicatorOutput
from a_domain.types.values import FormulaId


class IndicatorReadings:
    """
    Reads every indicator of the strategy at each daily bar a stock was evaluated on, so a chart can draw the same
    values the strategy's rules read. It decides nothing.
    """

    def execute(self, stock: Stock, strategy: TechnicalStrategy) -> dict[FormulaId, list[dict[IndicatorOutput, float]]]:
        bars = sorted(stock.ohlcv, key=lambda bar: bar.ts)
        return {indicator_id: indicator_series(parameters, bars) for indicator_id, parameters in strategy.indicators.items()}
