"""
Every HTTPS client that reads TWSE, TPEX, MOPS, MIS, cnyes, Yahoo or PTT data verifies the server's certificate, and
the news and PTT clients send the headers the `sources` settings name.
"""

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from support.settings import shipped_config
from trading_stack import MONDAY_10_00, MovableClock, SilentLogger, StockDirectory

from a_domain.model.market.stock import Stock
from a_domain.types.values import FiscalQuarter
from b_application.config.market_data_config import MarketDataConfig, MarketHoursConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.feed.news.cnyes_news_provider import CnyesNewsProvider
from c_infrastructure.feed.news.yahoo_tw_news_provider import YahooTwNewsProvider
from c_infrastructure.feed.ptt_provider import PttProvider
from c_infrastructure.market.mis_quote_provider import MisQuoteProvider
from c_infrastructure.market.mops_fundamentals_provider import MopsFundamentalsProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.system.market_clock import TaiwanMarketClock

SOURCES = shipped_config().sources

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
    return opened


async def test_exchange_clients_keep_certificate_verification_on(clients: list[dict[str, Any]], tmp_path: Path) -> None:
    db = DatabaseConnector(config=shipped_config(tmp_path), logger=SilentLogger())
    await db.init_db()
    unspaced = SOURCES.mops.model_copy(update={"request_interval_seconds": 0.0})
    mops = MopsFundamentalsProvider(
        db=db, market_clock=MovableClock(MONDAY_10_00), mops=unspaced, logger=SilentLogger(), write_lock=asyncio.Lock()
    )

    try:
        await TaiwanStockProvider(
            exchange=SOURCES.exchange,
            market_clock=TaiwanMarketClock(MarketHoursConfig()),
            market_data=MarketDataConfig(),
            logger=SilentLogger(),
        ).get_all()
        await mops.fetch_industries()
        await mops.fetch_cumulative_eps([FiscalQuarter(2026, 3)])
        await MisQuoteProvider(SOURCES.exchange, MarketDataConfig(), SilentLogger()).fetch_realtime_bars([Stock(stock_id="2330")])
    finally:
        await db.close()

    assert len(clients) == 6
    assert [client.get("verify", True) for client in clients] == [True] * 6


async def test_news_and_ptt_clients_keep_certificate_verification_on(clients: list[dict[str, Any]], tmp_path: Path) -> None:
    CnyesNewsProvider(SOURCES.news, SilentLogger())
    YahooTwNewsProvider(SOURCES.news, SilentLogger())
    PttProvider(config=shipped_config(tmp_path), logger=SilentLogger(), stock_provider=StockDirectory())

    assert len(clients) == 3
    assert [client.get("verify", True) for client in clients] == [True] * 3


async def test_news_and_ptt_clients_send_the_headers_their_settings_name(clients: list[dict[str, Any]], tmp_path: Path) -> None:
    config = shipped_config(tmp_path)
    CnyesNewsProvider(SOURCES.news, SilentLogger())
    YahooTwNewsProvider(SOURCES.news, SilentLogger())
    PttProvider(config=config, logger=SilentLogger(), stock_provider=StockDirectory())

    assert [client["headers"] for client in clients] == [
        {"Accept": "application/json", "User-Agent": SOURCES.news.cnyes_user_agent},
        {"User-Agent": SOURCES.news.yahoo_user_agent},
        {"User-Agent": config.sources.ptt.user_agent, "Cookie": config.sources.ptt.cookie},
    ]
