from datetime import date, datetime, time, timedelta

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.rules.market.breadth import Breadth, MarketBreadth, MarketBreadthRule
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

SESSION = date(2026, 11, 3)


def close(price: float, change: float | None, session: date = SESSION) -> Ohlcv:
    """A listing close stamped at its session's 13:30 close; its reference price is price - change."""
    ts = datetime.combine(session, time(13, 30), TAIWAN_TIMEZONE)
    return Ohlcv(ts=ts, open=price, high=price, low=price, close=price, volume=1000, change=change)


def test_breadth_counts_each_stock_once_overall_and_in_its_industry() -> None:
    closes = {"2330": close(101, 1), "2303": close(98, -2), "1101": close(50, 0), "0050": close(105, 5)}
    industries = {"2330": "半導體業", "2303": "半導體業", "1101": "水泥工業"}

    assert MarketBreadthRule().apply(closes, industries) == MarketBreadth(
        session_close=closes["2330"].ts,
        market=Breadth(advancers=2, decliners=1, unchanged=1, average_change_percent=1.0),
        industries={
            "半導體業": Breadth(advancers=1, decliners=1, unchanged=0, average_change_percent=-0.5),
            "水泥工業": Breadth(advancers=0, decliners=0, unchanged=1, average_change_percent=0.0),
        },
    )


def test_only_the_latest_session_with_a_reported_change_counts() -> None:
    """A listing not updated yet still holds the session before; a bar from another source has no change."""
    closes = {"2330": close(101, 1), "6488": close(756, -58, SESSION - timedelta(days=1)), "8069": close(149, None)}

    breadth = MarketBreadthRule().apply(closes, {"2330": "半導體業", "6488": "半導體業", "8069": "光電業"})

    assert breadth is not None
    assert breadth.session_close == closes["2330"].ts
    assert breadth.market == Breadth(advancers=1, decliners=0, unchanged=0, average_change_percent=1.0)
    assert list(breadth.industries) == ["半導體業"]


def test_a_listing_without_changes_has_no_breadth() -> None:
    assert MarketBreadthRule().apply({}, {}) is None
    assert MarketBreadthRule().apply({"2330": close(101, None)}, {"2330": "半導體業"}) is None
