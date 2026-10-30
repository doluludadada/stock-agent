from datetime import datetime, timedelta

import pytest

from a_domain.model.indicators.technical_indicators import MovingAverages, TechnicalIndicators
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.technical.criteria.base import TechnicalCriterion
from a_domain.rules.technical.criteria.volume import LiquidityCriterion, VolumeExpansionCriterion


def stock_with_volumes(volumes: list[int], volume_ma: dict[int, float]) -> Stock:
    start = datetime(2026, 6, 1)
    bars = [Ohlcv(ts=start + timedelta(days=index), close=20, volume=volume) for index, volume in enumerate(volumes)]
    return Stock(stock_id="2330", ohlcv=bars, indicators=TechnicalIndicators(ma=MovingAverages(volume_ma=volume_ma)))


@pytest.mark.parametrize(
    ("criterion", "stock", "passed"),
    [
        (VolumeExpansionCriterion(min_ratio=1.0), stock_with_volumes([], {5: 1000.0}), False),
        (VolumeExpansionCriterion(min_ratio=1.0), stock_with_volumes([1000], {}), False),
        (VolumeExpansionCriterion(min_ratio=1.0, period=10), stock_with_volumes([1000], {5: 1000.0}), False),
        (VolumeExpansionCriterion(min_ratio=1.0), stock_with_volumes([999], {5: 1000.0}), False),
        (VolumeExpansionCriterion(min_ratio=1.0), stock_with_volumes([1000], {5: 1000.0}), True),
        (LiquidityCriterion(min_daily_volume=500), stock_with_volumes([], {}), False),
        (LiquidityCriterion(min_daily_volume=500), stock_with_volumes([9000, 400, 400, 400, 400, 400], {}), False),
        (LiquidityCriterion(min_daily_volume=500), stock_with_volumes([600, 400], {}), True),
    ],
)
def test_volume_criteria(criterion: TechnicalCriterion, stock: Stock, passed: bool) -> None:
    assert criterion.apply(stock) is passed
