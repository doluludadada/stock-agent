import json
from datetime import UTC, datetime

import httpx
import pytest
from support.settings import shipped_config

from a_domain.model.trading.signal import TradeSignal
from a_domain.types.enums import SignalSource, TradeAction
from b_application.config.chat_config import LineConfig
from c_infrastructure.platforms.line import line_notification_adapter
from c_infrastructure.platforms.line.line_notification_adapter import LineNotificationAdapter

pytestmark = pytest.mark.asyncio

GENERATED_AT = datetime(2026, 10, 30, 2, 0, tzinfo=UTC)


class SilentLogger:
    def __getattr__(self, name: str):
        return lambda message: None


def signal(action: TradeAction) -> TradeSignal:
    return TradeSignal(
        stock_id="2330",
        action=action,
        quantity=1000,
        price_at_signal=1015.0,
        price_observed_at=GENERATED_AT,
        source=SignalSource.COMBINED,
        score=86,
        reason="Strong revenue growth",
        generated_at=GENERATED_AT,
    )


@pytest.fixture
def line_api(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={}, request=request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        line_notification_adapter.httpx, "AsyncClient", lambda **options: real_client(transport=httpx.MockTransport(answer))
    )
    return sent


def adapter(token: str | None = "line-token") -> LineNotificationAdapter:
    config = shipped_config().model_copy(update={"line": LineConfig(LINE_CHANNEL_ACCESS_TOKEN=token)})
    return LineNotificationAdapter(config=config, logger=SilentLogger())


async def test_a_signal_alert_is_multicast_to_every_recipient(line_api: list[httpx.Request]) -> None:
    assert await adapter().send_signal_alert(signal(TradeAction.SELL), ["U1", "U2"]) is True

    [request] = line_api
    assert str(request.url) == shipped_config().sources.line.multicast_url
    assert request.headers["Authorization"] == "Bearer line-token"
    body = json.loads(request.content)
    assert body["to"] == ["U1", "U2"]
    assert body["messages"][0]["type"] == "text"
    assert body["messages"][0]["text"].split("\n")[1:] == [
        "──────────────",
        "Action : sell",
        "Stock  : 2330",
        "Price  : 1015.0",
        "Volume : 1000 shares",
        "Score  : 86/100",
        "──────────────",
        "Reason : Strong revenue growth",
    ]


@pytest.mark.parametrize(("token", "recipients"), [(None, ["U1"]), ("line-token", [])])
async def test_no_alert_is_sent_without_a_token_or_recipients(
    token: str | None, recipients: list[str], line_api: list[httpx.Request]
) -> None:
    assert await adapter(token).send_signal_alert(signal(TradeAction.BUY), recipients) is False
    assert line_api == []


@pytest.mark.parametrize(("action", "marker"), [(TradeAction.BUY, "🟢"), (TradeAction.SELL, "🔴")])
async def test_a_buy_alert_is_marked_green_and_a_sell_alert_red(
    action: TradeAction, marker: str, line_api: list[httpx.Request]
) -> None:
    await adapter().send_signal_alert(signal(action), ["U1"])

    [request] = line_api
    assert json.loads(request.content)["messages"][0]["text"].split("\n")[0] == f"{marker} TW-Stock-Agent Alert"
