"""Every HTTPS client that reads TWSE, TPEX, MOPS or MIS data verifies the server's certificate."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from trading_stack import MONDAY_10_00, MovableClock, SilentLogger

from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter
from a_domain.model.market.stock import Stock
from b_application.config.app_config import AppConfig
from b_application.config.sources_config import SourcesConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.market.mis_quote_provider import MisQuoteProvider
from c_infrastructure.market.mops_fundamentals_provider import MopsFundamentalsProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider

SOURCES = SourcesConfig()

pytestmark = pytest.mark.asyncio


@pytest.fixture
def clients(monkeypatch) -> list[dict[str, Any]]:
    """The keyword arguments of every httpx.AsyncClient the providers open. Each request gets an empty answer."""
    opened: list[dict[str, Any]] = []
    real_client = httpx.AsyncClient

    def answer(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text="<html>查詢無資料</html>")
        if str(request.url).startswith(SOURCES.exchange.mis_quotes_url):
            return httpx.Response(200, json={"rtcode": "0000", "msgArray": []})
        return httpx.Response(200, json=[])

    def open_client(**kwargs) -> httpx.AsyncClient:
        opened.append(kwargs)
        return real_client(transport=httpx.MockTransport(answer))

    monkeypatch.setattr(httpx, "AsyncClient", open_client)
    monkeypatch.setattr(MopsFundamentalsProvider, "REQUEST_INTERVAL_SECONDS", 0.0)
    return opened


async def test_exchange_clients_keep_certificate_verification_on(clients: list[dict[str, Any]], tmp_path: Path) -> None:
    db = DatabaseConnector(config=AppConfig(project_root=tmp_path), logger=SilentLogger())
    await db.init_db()
    mops = MopsFundamentalsProvider(db=db, market_clock=MovableClock(MONDAY_10_00), mops=SOURCES.mops, logger=SilentLogger())

    try:
        await TaiwanStockProvider(exchange=SOURCES.exchange, logger=SilentLogger()).get_all()
        await mops.fetch_industries()
        await mops.fetch_cumulative_eps([FiscalQuarter(2026, 3)])
        await MisQuoteProvider(SOURCES.exchange, SilentLogger()).fetch_realtime_bars([Stock(stock_id="2330")])
    finally:
        await db.close()

    assert len(clients) == 5
    assert [client.get("verify", True) for client in clients] == [True] * 5
