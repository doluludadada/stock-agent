from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pytest

from a_domain.model.market.stock import Stock
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider


@pytest.mark.asyncio
async def test_history_drops_zero_volume_placeholder_for_closed_market_day(monkeypatch) -> None:
    # Yahoo's 2330.TW response for the 2026-10-23 typhoon closure: a flat bar at the prior close with no volume.
    rows = {
        ("2330.TW", "Open"): [2435.0, 2385.0],
        ("2330.TW", "High"): [2435.0, 2385.0],
        ("2330.TW", "Low"): [2385.0, 2385.0],
        ("2330.TW", "Close"): [2385.0, 2385.0],
        ("2330.TW", "Volume"): [22930116, 0],
    }
    df = pd.DataFrame(rows, index=pd.to_datetime(["2026-10-22", "2026-10-23"]))
    provider = YahooFinanceProvider(cast(Any, SimpleNamespace(info=lambda message: None)), delay_seconds=0)

    async def fake_download(**kwargs) -> pd.DataFrame:
        return df

    monkeypatch.setattr(provider, "_download", fake_download)

    history = await provider.fetch_history([Stock(stock_id="2330")], datetime(2026, 10, 1), datetime(2026, 10, 26))

    assert [bar.ts.date().isoformat() for bar in history["2330"]] == ["2026-10-22"]
