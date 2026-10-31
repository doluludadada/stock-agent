import math

import pytest
from icontract.errors import ViolationError

from a_domain.model.indicators.moving_averages import MovingAverages


@pytest.mark.parametrize(
    "moving_averages",
    [
        {"price_ma": {0: 100.0}},
        {"price_ma": {-5: 100.0}},
        {"price_ma": {20: 0.0}},
        {"price_ma": {20: -1.0}},
        {"price_ma": {20: math.nan}},
        {"price_ma": {20: math.inf}},
        {"volume_ma": {0: 1000.0}},
        {"volume_ma": {5: 0.0}},
        {"volume_ma": {5: math.nan}},
    ],
)
def test_moving_averages_reject_non_positive_periods_and_values(moving_averages: dict[str, dict[int, float]]) -> None:
    with pytest.raises(ViolationError):
        MovingAverages(**moving_averages)


def test_moving_averages_accept_positive_periods_and_values() -> None:
    moving_averages = MovingAverages(price_ma={5: 10.0, 20: 9.5}, volume_ma={5: 1200.0})

    assert moving_averages.price_ma[20] == 9.5
