import math
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest
import yfinance
from support.fakes import RecordingLogger

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.types.enums import MarketType
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

NAN = math.nan
PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
TSMC = Stock(stock_id="2330")
PEGAVISION = Stock(stock_id="6488", market=MarketType.TPEX)
UNLISTED = Stock(stock_id="9999")


def yahoo_frame(index: pd.DatetimeIndex, rows_by_ticker: dict[str, list[tuple]]) -> pd.DataFrame:
    """The layout yf.download(group_by="ticker", auto_adjust=False) returns for one or many tickers."""
    frames = {ticker: pd.DataFrame(rows, index=index, columns=PRICE_COLUMNS) for ticker, rows in rows_by_ticker.items()}
    return pd.concat(frames.values(), axis=1, keys=frames.keys(), names=["Ticker", "Price"])


def session(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 13, 30, tzinfo=TAIWAN_TIMEZONE)


def daily(*days: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(days, name="Date")


@pytest.fixture
def yahoo(monkeypatch) -> SimpleNamespace:
    """Stands in for yf.download: returns the queued frames in order and records every request."""
    fake = SimpleNamespace(calls=[], frames=[])

    def download(**kwargs):
        fake.calls.append(kwargs)
        return fake.frames.pop(0)

    monkeypatch.setattr(yfinance, "download", download)
    return fake


def provider(batch_size: int = 50) -> YahooFinanceProvider:
    return YahooFinanceProvider(RecordingLogger(), batch_size=batch_size, delay_seconds=0)


def assert_requested(call: dict, tickers: list[str], **params) -> None:
    assert call["tickers"] == tickers
    assert call["group_by"] == "ticker"
    assert call["auto_adjust"] is False
    assert call.get("multi_level_index", True) is True
    for name in ("start", "end", "period", "interval"):
        assert call.get(name) == params.get(name), name


@pytest.mark.asyncio
async def test_history_returns_daily_bars_per_stock_stamped_at_their_session_close(yahoo) -> None:
    yahoo.frames.append(
        yahoo_frame(
            daily("2026-10-29", "2026-10-30"),
            {
                "6488.TWO": [(850.0, 853.0, 803.0, 814.0, 814.0, 7045788), (775.0, 779.0, 741.0, 756.0, 756.0, 9821343)],
                "2330.TW": [(2420.0, 2425.0, 2390.0, 2415.0, 2415.0, 16872114), (2380.0, 2380.0, 2360.0, 2370.0, 2370.0, 34795531)],
                "9999.TW": [(NAN,) * 6, (NAN,) * 6],
            },
        )
    )

    history = await provider().fetch_history([TSMC, PEGAVISION, UNLISTED], datetime(2026, 10, 20), datetime(2026, 10, 30))

    assert_requested(yahoo.calls[0], ["2330.TW", "6488.TWO", "9999.TW"], start="2026-10-20", end="2026-10-31", interval="1d")
    assert list(history) == ["2330", "6488"]
    assert history["2330"] == [
        Ohlcv(ts=session(2026, 10, 29), open=2420.0, high=2425.0, low=2390.0, close=2415.0, volume=16872114, adj_close=2415.0),
        Ohlcv(ts=session(2026, 10, 30), open=2380.0, high=2380.0, low=2360.0, close=2370.0, volume=34795531, adj_close=2370.0),
    ]
    assert history["6488"] == [
        Ohlcv(ts=session(2026, 10, 29), open=850.0, high=853.0, low=803.0, close=814.0, volume=7045788, adj_close=814.0),
        Ohlcv(ts=session(2026, 10, 30), open=775.0, high=779.0, low=741.0, close=756.0, volume=9821343, adj_close=756.0),
    ]


@pytest.mark.asyncio
async def test_history_drops_zero_volume_placeholder_for_closed_market_day(yahoo) -> None:
    # Yahoo's 2330.TW response for the 2026-10-23 typhoon closure: a flat bar at the prior close with no volume.
    yahoo.frames.append(
        yahoo_frame(
            daily("2026-10-22", "2026-10-23"),
            {
                "2330.TW": [(2435.0, 2435.0, 2385.0, 2385.0, 2385.0, 22930116), (2385.0, 2385.0, 2385.0, 2385.0, 2385.0, 0)],
                "6488.TWO": [(812.0, 812.0, 812.0, 812.0, 812.0, 0), (812.0, 812.0, 812.0, 812.0, 812.0, 0)],
            },
        )
    )

    history = await provider().fetch_history([TSMC, PEGAVISION], datetime(2026, 10, 1), datetime(2026, 10, 26))

    assert [bar.ts.date().isoformat() for bar in history["2330"]] == ["2026-10-22"]
    assert "6488" not in history


@pytest.mark.asyncio
async def test_history_skips_rows_without_close_and_fills_other_missing_values(yahoo) -> None:
    yahoo.frames.append(
        yahoo_frame(
            daily("2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31"),
            {
                "2330.TW": [
                    (2420.0, 2430.0, 2410.0, NAN, NAN, 19880613),
                    (NAN, NAN, NAN, 2415.0, NAN, 16872114),
                    (2380.0, 2380.0, 2360.0, 2370.0, 2370.0, NAN),
                    (2375.0, 2380.0, 2370.0, 2372.0, 2372.0, 1200),
                ]
            },
        )
    )

    history = await provider().fetch_history([TSMC], datetime(2026, 10, 28), datetime(2026, 10, 31))

    assert history["2330"] == [
        Ohlcv(ts=session(2026, 10, 29), open=2415.0, high=2415.0, low=2415.0, close=2415.0, volume=16872114, adj_close=None),
        Ohlcv(ts=session(2026, 10, 31), open=2375.0, high=2380.0, low=2370.0, close=2372.0, volume=1200, adj_close=2372.0),
    ]


@pytest.mark.asyncio
async def test_unknown_ticker_and_empty_download_return_no_bars(yahoo) -> None:
    yahoo.frames.append(yahoo_frame(daily(), {"9999.TW": []}))
    yahoo.frames.append(pd.DataFrame())
    yahoo.frames.append(yahoo_frame(daily("2026-10-30"), {"2330.TW": [(2380.0, 2380.0, 2360.0, 2370.0, 2370.0, 34795531)]}))
    yahoo.frames.append(None)

    assert await provider().fetch_history([UNLISTED], datetime(2026, 10, 30), datetime(2026, 10, 30)) == {}
    assert await provider().fetch_history([TSMC], datetime(2026, 10, 30), datetime(2026, 10, 30)) == {}
    assert await provider().fetch_history([PEGAVISION], datetime(2026, 10, 30), datetime(2026, 10, 30)) == {}
    assert await provider().fetch_history([TSMC], datetime(2026, 10, 30), datetime(2026, 10, 30)) == {}


@pytest.mark.asyncio
async def test_stocks_are_deduplicated_and_requested_in_batches(yahoo) -> None:
    stocks = [Stock(stock_id=stock_id) for stock_id in ("2330", "2317", "2330", "2454", "2317", "2303")]
    yahoo.frames.extend([pd.DataFrame()] * 2)

    assert await provider(batch_size=2).fetch_history(stocks, datetime(2026, 10, 1), datetime(2026, 10, 30)) == {}
    assert [call["tickers"] for call in yahoo.calls] == [["2330.TW", "2317.TW"], ["2454.TW", "2303.TW"]]


@pytest.mark.asyncio
async def test_no_stocks_means_no_request(yahoo) -> None:
    assert await provider().fetch_history([], datetime(2026, 10, 1), datetime(2026, 10, 30)) == {}
    assert yahoo.calls == []


@pytest.mark.asyncio
async def test_download_failure_propagates(monkeypatch) -> None:
    def download(**kwargs):
        raise ConnectionError("Yahoo unreachable")

    monkeypatch.setattr(yfinance, "download", download)

    with pytest.raises(ConnectionError):
        await provider().fetch_history([TSMC], datetime(2026, 10, 1), datetime(2026, 10, 30))
