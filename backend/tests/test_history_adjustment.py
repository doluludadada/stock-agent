"""
The open-data archive keeps each stock's daily bars as its exchange listed them and adjusts them on read for the
corporate actions between them (HistoryAdjustmentRule). Every row here is a real one, read on 2026-11-06: the stock's
bars as TWSE's daily trading report of the stock (STOCK_DAY) lists them, and the TAIEX close and change of each session
(FMTQIK).
"""

from dataclasses import replace
from datetime import date

import pytest

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.rules.market.listing import HistoryAdjustmentRule
from a_domain.types.enums import MarketType
from b_application.config.market_data_config import MarketHoursConfig
from c_infrastructure.system.market_clock import TaiwanMarketClock

CLOCK = TaiwanMarketClock(MarketHoursConfig())


def adjusted_on_twse(history: list[Ohlcv], index: list[Ohlcv]) -> list[Ohlcv]:
    return HistoryAdjustmentRule().apply(history, index, MarketType.TWSE)


def session(roc_date: str) -> date:
    year, month, day = (int(part) for part in roc_date.split("/"))
    return date(year + 1911, month, day)


def bars(rows: list[tuple[str, float, float, float, float, int, str]]) -> list[Ohlcv]:
    """A stock's rows as STOCK_DAY lists them, its X0.00 (TWSE compared the close to no reference) read as a change of 0."""
    return [
        Ohlcv(
            ts=CLOCK.session_close(session(day)),
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            change=float(change.removeprefix("X")),
        )
        for day, open_, high, low, close, volume, change in rows
    ]


def taiex(rows: list[tuple[str, float, float]]) -> list[Ohlcv]:
    return [
        Ohlcv(ts=CLOCK.session_close(session(day)), open=close, high=close, low=close, close=close, change=change)
        for day, close, change in rows
    ]


def closes(history: list[Ohlcv]) -> list[float]:
    return [round(bar.close, 2) for bar in history]


SPLIT_0050 = [
    ("114/06/09", 183.40, 184.05, 183.05, 183.70, 14115012, "+1.75"),
    ("114/06/10", 184.90, 188.90, 184.90, 188.65, 31483080, "+4.95"),
    ("114/06/18", 47.50, 47.72, 47.14, 47.57, 252639825, "+0.41"),
    ("114/06/19", 47.50, 47.55, 47.02, 47.10, 173652638, "-0.47"),
]
"""0050 split one unit into four: trading stopped after 2025-06-10, and the new units traded from 2025-06-18."""

TAIEX_2025_06 = [
    ("114/06/05", 21674.43, 56.34),
    ("114/06/06", 21660.66, -13.77),
    ("114/06/09", 21790.29, 129.63),
    ("114/06/10", 22242.14, 451.85),
    ("114/06/11", 22470.10, 227.96),
    ("114/06/12", 22287.82, -182.28),
    ("114/06/13", 22072.95, -214.87),
    ("114/06/16", 22049.90, -23.05),
    ("114/06/17", 22211.59, 161.69),
    ("114/06/18", 22356.73, 145.14),
    ("114/06/19", 22003.50, -353.23),
]


def test_a_split_scales_every_earlier_bar_by_the_reference_the_exchange_compared_the_new_units_to() -> None:
    adjusted = adjusted_on_twse(bars(SPLIT_0050), taiex(TAIEX_2025_06))

    assert closes(adjusted) == [45.92, 47.16, 47.57, 47.10]
    assert [round(bar.high, 2) for bar in adjusted[:2]] == [46.01, 47.22]
    assert adjusted[1].volume == pytest.approx(31483080 * 4, rel=1e-4)
    assert adjusted[2:] == bars(SPLIT_0050)[2:]


def test_the_stored_change_of_an_adjusted_bar_is_scaled_with_its_prices() -> None:
    adjusted = adjusted_on_twse(bars(SPLIT_0050), taiex(TAIEX_2025_06))

    assert adjusted[1].change == pytest.approx(4.95 * 47.16 / 188.65)


def test_no_factor_crosses_a_session_the_archive_missed() -> None:
    held = [row for row in SPLIT_0050 if row[0] != "114/06/10"]
    missed = [row for row in TAIEX_2025_06 if row[0] != "114/06/10"]
    rows = [("114/06/05", 182.00, 182.65, 181.50, 181.65, 10845068, "+0.35"), ("114/06/09", *SPLIT_0050[0][1:])]

    assert closes(adjusted_on_twse(bars(held), taiex(missed))) == [183.70, 47.57, 47.10]
    assert closes(adjusted_on_twse(bars(rows), taiex([row for row in TAIEX_2025_06 if row[0] != "114/06/06"]))) == [181.65, 183.70]


def test_no_factor_crosses_a_session_the_index_was_not_archived_on() -> None:
    adjusted = adjusted_on_twse(bars(SPLIT_0050), taiex([row for row in TAIEX_2025_06 if row[0] != "114/06/18"]))

    assert closes(adjusted) == [183.70, 188.65, 47.57, 47.10]


CAPITAL_REDUCTION_2321 = [
    ("115/09/08", 14.10, 14.40, 13.80, 13.80, 10805, "-0.60"),
    ("115/09/09", 14.80, 15.10, 14.80, 15.10, 10201, "+1.30"),
    ("115/09/21", 27.60, 27.60, 26.00, 26.00, 4626, "X0.00"),
    ("115/09/22", 26.00, 26.00, 23.70, 23.90, 9792, "-2.10"),
]
"""2321 reduced its capital to offset losses: trading stopped after 2026-09-09 and resumed on 2026-09-21 at 27.61."""

TAIEX_2026_09 = [
    ("115/09/08", 47105.78, -220.49),
    ("115/09/09", 47183.36, 77.58),
    ("115/09/10", 46940.49, -242.87),
    ("115/09/11", 46184.85, -755.64),
    ("115/09/14", 45862.52, -322.33),
    ("115/09/15", 45511.49, -351.03),
    ("115/09/16", 45848.90, 337.41),
    ("115/09/17", 46288.00, 439.10),
    ("115/09/18", 47180.75, 892.75),
    ("115/09/21", 47718.84, 538.09),
    ("115/09/22", 47800.17, 81.33),
]


@pytest.mark.parametrize("change", [0.0, None], ids=["X0.00 read as 0", "X0.00 left unread"])
def test_a_capital_reduction_resumed_on_a_day_the_exchange_compares_to_no_reference_gets_no_factor(change: float | None) -> None:
    history = bars(CAPITAL_REDUCTION_2321)
    history[2] = replace(history[2], change=change)

    assert closes(adjusted_on_twse(history, taiex(TAIEX_2026_09))) == [13.80, 15.10, 26.00, 23.90]


EX_DIVIDEND_0050 = [
    ("114/07/17", 50.60, 50.80, 50.30, 50.70, 89861784, "+0.30"),
    ("114/07/18", 51.40, 51.60, 51.30, 51.45, 107920505, "+0.75"),
    ("114/07/21", 51.10, 51.10, 50.75, 50.90, 78953424, "X0.00"),
    ("114/07/22", 50.90, 51.30, 50.45, 50.55, 92162175, "-0.35"),
]

TAIEX_2025_07 = [
    ("114/07/17", 23113.28, 70.38),
    ("114/07/18", 23383.13, 269.85),
    ("114/07/21", 23340.56, -42.57),
    ("114/07/22", 22987.92, -352.64),
]


def test_an_ex_dividend_day_the_exchange_compares_to_no_reference_gets_no_factor() -> None:
    adjusted = adjusted_on_twse(bars(EX_DIVIDEND_0050), taiex(TAIEX_2025_07))

    assert adjusted == bars(EX_DIVIDEND_0050)


EX_DIVIDEND_8467 = [
    ("115/11/02", 96.10, 96.40, 96.00, 96.40, 3262, "-0.60"),
    ("115/11/03", 96.50, 96.90, 92.90, 92.90, 33709, "-3.50"),
    ("115/11/04", 92.50, 92.50, 88.00, 88.00, 20647, "-2.90"),
    ("115/11/05", 96.80, 96.80, 96.80, 96.80, 97604, "+8.80"),
]
"""
8467 went ex-dividend on 2026-11-04 with 2.00 cash (TWT48U), so its reference was 92.90 - 2.00 = 90.90; TWSE wrote X0.00,
and this is the change had it compared the close to that reference, as it does on a split.
"""

TAIEX_2026_11 = [
    ("115/11/02", 44920.14, -291.69),
    ("115/11/03", 43307.54, -1612.60),
    ("115/11/04", 42948.91, -358.63),
    ("115/11/05", 41574.72, -1374.19),
]


def test_a_cash_dividend_the_exchange_compares_to_its_reference_is_adjusted_like_any_other_action() -> None:
    adjusted = adjusted_on_twse(bars(EX_DIVIDEND_8467), taiex(TAIEX_2026_11))

    assert closes(adjusted) == [94.32, 90.90, 88.00, 96.80]


def test_a_normal_session_and_an_empty_history_change_nothing() -> None:
    history = bars(SPLIT_0050[2:])

    assert adjusted_on_twse(history, taiex(TAIEX_2025_06)) == history
    assert adjusted_on_twse([], taiex(TAIEX_2025_06)) == []
    assert adjusted_on_twse(history, []) == history


UNTRADED_2064 = [
    ("115/10/13", 11.95, 12.20, 11.80, 11.80, 327000, "-0.10"),
    ("115/10/15", 11.65, 11.75, 11.60, 11.70, 7000, "-0.15"),
    ("115/10/16", 11.85, 12.10, 11.70, 11.70, 299000, "0.00"),
]
"""
TPEX's 2064 did not trade on 2026-10-14, and TPEX compared its next close to a reference it moved to 11.85, not to its
last close of 11.80; TWSE writes X0.00 on such a day (1213 on 2026-10-20).
"""

TPEX_INDEX_2026_10 = [
    ("115/10/13", 414.31, -13.59),
    ("115/10/14", 420.13, 5.82),
    ("115/10/15", 396.90, -23.23),
    ("115/10/16", 400.26, 3.36),
]


def test_a_tpex_stock_gets_no_factor_across_a_session_it_did_not_trade() -> None:
    history = bars(UNTRADED_2064)

    assert HistoryAdjustmentRule().apply(history, taiex(TPEX_INDEX_2026_10), MarketType.TPEX) == history
