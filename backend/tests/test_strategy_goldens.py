"""
What every caller of the technical strategy observes, to the last bit, as the scalar implementation it replaced reported
it at c4d4dde1: each strategy's report on each case, and each indicator's reading at every bar of each case. The cases
in tests/fixtures/technical/strategy_goldens.json are cut from six daily histories: random walks, prices flat for weeks,
closes repeated exactly, sessions without volume, infinite prices and windows too short for a strategy or an indicator,
two thirds of them with a realtime quote. The strategies are the built-in one and six random ones that together read
every output of every indicator kind with every operator; the indicators are one random and one built-in of each kind.

Three readings are the kernel's own. The scalar implementation squared a Bollinger band's distances with `**`, which
is the C library's pow, and pow rounds its last bit differently from one machine to the next; the kernel multiplies,
which every machine rounds alike. So three cases of the 20-bar band differ from the scalar readings, by under 2e-15 of
each value, and no report differs.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from a_domain.model.analysis.technical_report import TechnicalObservation, TechnicalReport
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.technical.calculation.calculator import IndicatorParameters, indicator_series
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.types.enums import IndicatorOutput

GOLDENS = json.loads((Path(__file__).parent / "fixtures" / "technical" / "strategy_goldens.json").read_text())
FIRST_SESSION = datetime(2026, 1, 5, 13, 30, tzinfo=UTC)


def case_stock(row: str, first: int, last: int, realtime_close: float | None) -> Stock:
    """The row's bars from `first` up to `last`, oldest first, a day apart, and the realtime quote if there is one."""
    bars = [
        Ohlcv(ts=FIRST_SESSION + timedelta(days=day), open=opening, high=high, low=low, close=close, volume=volume)
        for day, (opening, high, low, close, volume) in enumerate(GOLDENS["rows"][row])
    ]
    stock = Stock(stock_id=f"{row}[{first}:{last}]")
    stock.load_history(bars[first:last])

    if realtime_close is not None:
        stock.realtime_bar = Ohlcv(ts=bars[last - 1].ts + timedelta(hours=8), close=realtime_close, volume=1000)

    return stock


CASES = [case_stock(*case) for case in GOLDENS["cases"]]


def golden_report(score: int, hard_failures: list[str], soft_failures: list[str], observations: list[Any]) -> TechnicalReport:
    detected = [TechnicalObservation(rule=rule, detected=pattern) for rule, pattern in observations]
    return TechnicalReport(score=score, hard_failures=hard_failures, soft_failures=soft_failures, observations=detected)


def series_digest(series: list[dict[IndicatorOutput, float]]) -> str:
    """Every output at every bar by its exact bits."""
    canonical = repr([sorted((str(output), float(value).hex()) for output, value in outputs.items()) for outputs in series])
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


@pytest.mark.parametrize("document", GOLDENS["strategies"], ids=lambda document: document["strategy_id"])
def test_each_strategy_reports_every_case_at_once_as_the_scalar_strategy_did_one_at_a_time(document: dict[str, Any]) -> None:
    strategy = TypeAdapter(TechnicalStrategy).validate_python(document)

    assert strategy.apply(CASES) == [golden_report(*report) for report in GOLDENS["reports"][strategy.strategy_id]]


@pytest.mark.parametrize(
    ("number", "document"),
    enumerate(GOLDENS["indicators"]),
    ids=[f"{number}-{document['kind']}" for number, document in enumerate(GOLDENS["indicators"])],
)
def test_each_indicator_reads_every_bar_of_every_case_as_the_scalar_calculator_did(number: int, document: dict[str, Any]) -> None:
    indicator = TypeAdapter(IndicatorParameters).validate_python(document)

    assert [series_digest(indicator_series(indicator, stock.ohlcv)) for stock in CASES] == GOLDENS["readings"][number]
