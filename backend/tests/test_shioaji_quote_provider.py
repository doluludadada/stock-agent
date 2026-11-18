"""
A personal site's realtime quotes come from Shioaji's snapshots, stamped with the exchange's trade time, over the one
Shioaji login the process holds, which a Shioaji broker shares. A public site builds no Shioaji adapter, and a personal
site without a login has no quote, so it orders nothing.
"""

import asyncio
import threading
from datetime import datetime, timedelta

import pytest
import shioaji
from pydantic import SecretStr, ValidationError
from shioaji.error import TokenError
from support.fake_shioaji import FakeContracts, FakeShioaji, FakeStocks, snapshot, stock
from support.fakes import RecordingLogger
from support.settings import shipped_config, sinopac_setup
from trading_stack import MONDAY_10_00, SilentLogger, analysed_stock, open_stack

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.order import Order
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import Audience, MarketIndex, OrderStatus, ShioajiServer, SystemEnvironment
from a_domain.types.errors import RealtimeQuotesUnavailable
from b_application.config.app_config import AppConfig
from b_application.config.market_data_config import IndexQuoteContract, MarketDataConfig, MarketHoursConfig
from b_application.config.trading_config import ShioajiConfig, ShioajiLogin
from c_infrastructure.database.repositories.daily_close_archive import SqlDailyCloseArchive
from c_infrastructure.market.shioaji_quote_provider import ShioajiConnection, ShioajiQuoteProvider
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock
from d_presentation.dependencies import ProcessState, connect_shioaji

pytestmark = pytest.mark.asyncio


FRIDAY_AFTER_HOURS = datetime(2026, 10, 16, 14, 30, tzinfo=TAIWAN_TIMEZONE)
"""What a snapshot says over the weekend: the after-hours fixed-price trade of Friday's session."""


def process() -> ProcessState:
    return ProcessState(logger=SilentLogger(), attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())


def logged_in_client(**answers: datetime | None) -> FakeShioaji:
    """A client logged in with a contract per code, each answering a snapshot traded at its time, or untraded for None."""
    client = FakeShioaji(Contracts=FakeContracts(FakeStocks({code: stock(code) for code in answers})))
    client.login(api_key="key", secret_key="secret", subscribe_trade=False)
    client.snapshot_answers = {
        code: snapshot(code, traded_at or MONDAY_10_00.replace(hour=8, minute=30), 101.5, 0 if traded_at is None else 2_500)
        for code, traded_at in answers.items()
    }
    return client


CLOCK = TaiwanMarketClock(MarketHoursConfig())


def quote_provider(
    client: FakeShioaji, market_data: MarketDataConfig | None = None, logger: ILoggingProvider | None = None
) -> ShioajiQuoteProvider:
    return ShioajiQuoteProvider(
        connection=ShioajiConnection(client=client, up=True),
        new_client=FakeShioaji,
        login=ShioajiLogin(server=ShioajiServer.SIMULATION, api_key=SecretStr("key"), secret_key=SecretStr("secret")),
        market_clock=CLOCK,
        market_data=market_data or MarketDataConfig(quote_request_interval_seconds=0),
        board_lot_shares=1000,
        logger=logger or SilentLogger(),
    )


def shioaji_site(server: ShioajiServer, audience: Audience = Audience.PERSONAL) -> AppConfig:
    return sinopac_setup(shipped_config(), server).model_copy(update={"audience": audience})


async def test_a_quote_is_the_session_so_far_stamped_with_the_exchanges_trade_time_in_lots_of_shares() -> None:
    client = logged_in_client(**{"2330": FRIDAY_AFTER_HOURS, "6488": None})

    quotes = await quote_provider(client).fetch_realtime_bars([Stock(stock_id="2330"), Stock(stock_id="6488"), Stock(stock_id="9999")])

    assert quotes == {
        "2330": Ohlcv(ts=FRIDAY_AFTER_HOURS, open=101.5, high=101.5, low=101.5, close=101.5, volume=2_500_000, change=0.0)
    }
    assert quotes["2330"].ts.utcoffset() == timedelta(hours=8)


async def test_each_request_asks_for_at_most_a_batch_of_stocks_one_at_a_time_and_each_stock_once() -> None:
    codes = [f"{number:04d}" for number in range(1101, 1106)]
    client = logged_in_client(**dict.fromkeys(codes, FRIDAY_AFTER_HOURS))
    provider = quote_provider(client, MarketDataConfig(quote_batch_size=2, quote_request_interval_seconds=0.05))
    started = asyncio.get_running_loop().time()

    quotes = await provider.fetch_realtime_bars([Stock(stock_id=code) for code in [*codes, codes[0]]])

    assert client.snapshot_requests == [codes[0:2], codes[2:4], codes[4:5]]
    assert sorted(quotes) == codes
    assert asyncio.get_running_loop().time() - started >= 0.1


async def test_an_index_is_read_from_the_contract_the_settings_name_in_a_request_of_its_own() -> None:
    client = logged_in_client(**{"2330": MONDAY_10_00})
    client.snapshot_answers["001"] = snapshot("001", MONDAY_10_00, 41_040.08, 14_456_731, change=-2_635.04)
    provider = quote_provider(client)

    indexes = await provider.fetch_index_quotes(list(MarketIndex))
    quotes = await provider.fetch_realtime_bars([Stock(stock_id="2330")])

    assert client.snapshot_requests == [["001"], ["2330"]] and sorted(quotes) == ["2330"]
    assert indexes == {
        MarketIndex.TAIEX: Ohlcv(ts=MONDAY_10_00, open=41_040.08, high=41_040.08, low=41_040.08, close=41_040.08, change=-2_635.04)
    }
    assert await provider.fetch_index_quotes([]) == {} and len(client.snapshot_requests) == 2
    assert shipped_config().market_data.quote_index_contracts == {
        MarketIndex.TAIEX: IndexQuoteContract(exchange="TSE", symbol="TSE001")
    }


@pytest.mark.parametrize(
    ("contract", "total_volume", "requests", "warnings"),
    [
        (IndexQuoteContract(exchange="TSE", symbol="TSE001"), 0, 2, 0),
        (IndexQuoteContract(exchange="TSE", symbol="TSE999"), 14_456_731, 0, 1),
        (IndexQuoteContract(exchange="TWSE", symbol="TSE001"), 14_456_731, 0, 1),
        (None, 14_456_731, 0, 1),
    ],
    ids=[
        "no trade of the session yet",
        "a symbol Shioaji does not list",
        "an exchange Shioaji does not list",
        "no contract in the settings",
    ],
)
async def test_an_index_without_a_value_of_the_session_or_a_contract_gets_no_quote_and_is_warned_of_once(
    contract: IndexQuoteContract | None, total_volume: int, requests: int, warnings: int
) -> None:
    client = logged_in_client()
    client.snapshot_answers["001"] = snapshot("001", MONDAY_10_00, 41_040.08, total_volume)
    contracts = {} if contract is None else {MarketIndex.TAIEX: contract}
    logger = RecordingLogger()
    provider = quote_provider(client, MarketDataConfig(quote_request_interval_seconds=0, quote_index_contracts=contracts), logger)

    answers = [await provider.fetch_index_quotes([MarketIndex.TAIEX]) for _ in ("first round", "second round")]

    assert answers == [{}, {}] and len(client.snapshot_requests) == requests
    assert [message for level, message in logger.records if level == "warning"] == [
        "Shioaji quotes: no index contract for taiex, which gets no quote"
    ] * warnings


@pytest.mark.parametrize("name", ["keys", "_name", "tse", "TSE-001", ""])
async def test_an_index_contract_that_is_not_capitals_and_digits_is_refused_when_the_settings_load(name: str) -> None:
    for contract in ({"exchange": name, "symbol": "TSE001"}, {"exchange": "TSE", "symbol": name}):
        with pytest.raises(ValidationError):
            MarketDataConfig(quote_index_contracts={MarketIndex.TAIEX: contract})


async def test_an_index_request_shioaji_refuses_raises_its_type_alone_and_the_stocks_are_still_quoted() -> None:
    client = logged_in_client(**{"2330": MONDAY_10_00})
    client.refused_codes = frozenset({"001"})
    provider = quote_provider(client)

    with pytest.raises(RuntimeError, match="TimeoutError"):
        await provider.fetch_index_quotes([MarketIndex.TAIEX])

    assert sorted(await provider.fetch_realtime_bars([Stock(stock_id="2330")])) == ["2330"]
    assert client.snapshot_requests == [["001"], ["2330"]]


@pytest.mark.parametrize(
    ("traded_at", "status", "reason"),
    [
        (MONDAY_10_00 - timedelta(minutes=1), OrderStatus.FILLED, None),
        (FRIDAY_AFTER_HOURS, OrderStatus.REJECTED, "STALE_PRICE"),
        (None, OrderStatus.REJECTED, "STALE_PRICE"),
    ],
    ids=["fresh", "friday-after-hours", "no-trade-today"],
)
async def test_a_manual_buy_orders_on_a_fresh_snapshot_and_is_refused_on_a_stale_or_untraded_one(
    tmp_path, traded_at: datetime | None, status: OrderStatus, reason: str | None
) -> None:
    stack = await open_stack(tmp_path)
    client = logged_in_client(**{"2330": traded_at})
    stack.quotes.fetch_realtime_bars = quote_provider(client).fetch_realtime_bars

    result = (await stack.pipeline.buy_manually(analysed_stock())).require_manual_buy_order()

    assert isinstance(result, Order)
    assert (result.status, client.snapshot_requests) == (status, [["2330"]])
    assert reason is None or (result.reason is not None and result.reason.startswith(reason))
    assert status != OrderStatus.FILLED or result.average_filled_price == 101.5


async def test_without_a_shioaji_login_every_quote_is_refused_and_a_manual_buy_orders_nothing(tmp_path) -> None:
    stack = await open_stack(tmp_path)
    archive = SqlDailyCloseArchive(stack.db, stack.clock, shipped_config().sources.exchange, 7, SilentLogger())
    stack.quotes.fetch_realtime_bars = archive.fetch_realtime_bars

    with pytest.raises(RealtimeQuotesUnavailable, match="never a realtime quote. A personal site quotes on its Shioaji login"):
        await archive.fetch_realtime_bars([Stock(stock_id="2330")])

    status = await stack.pipeline.buy_manually(analysed_stock())

    assert [order.status for order in status.orders] == [OrderStatus.REJECTED]
    assert any("Shioaji key pair" in error for error in status.stats.errors)
    assert (await stack.broker.get_account()).cash == 1_000_000


async def test_quotes_and_a_shioaji_broker_share_one_login_that_every_runtime_of_the_process_reuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made: list[FakeShioaji] = []
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: made.append(FakeShioaji(simulation)) or made[-1])
    shared, site = process(), shioaji_site(ShioajiServer.SIMULATION)

    for _ in ("startup", "reload"):
        quotes, broker = await connect_shioaji(site, shared, CLOCK)
        [client] = made
        client.snapshot_answers = {"2330": snapshot("2330", FRIDAY_AFTER_HOURS, 101.5, 10)}
        assert quotes is not None and broker is not None
        assert (await quotes.fetch_realtime_bars([Stock(stock_id="2330")]))["2330"].ts == FRIDAY_AFTER_HOURS
        assert (await broker.get_account()).account_id == "0012345"

    assert (len(client.logins), client.logouts, client.simulation) == (1, 0, True)


@pytest.mark.parametrize("environment", [SystemEnvironment.DEV, SystemEnvironment.TEST])
async def test_the_simulation_server_reads_its_quotes_and_offers_sinopac_there_in_dev_and_test(
    environment: SystemEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[FakeShioaji] = []
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: made.append(FakeShioaji(simulation)) or made[-1])
    site = sinopac_setup(shipped_config(), ShioajiServer.SIMULATION, environment)

    quotes, broker = await connect_shioaji(site, process(), CLOCK)

    [client] = made
    assert quotes is not None and broker is not None and broker.link().simulation is True
    assert client.simulation and [login["api_key"] for login in client.logins] == ["SHIOAJI_API_KEY_TEST"]


async def test_a_public_site_builds_no_shioaji_client_and_has_no_quote() -> None:
    assert await connect_shioaji(shioaji_site(ShioajiServer.SIMULATION, Audience.PUBLIC), process(), CLOCK) == (None, None)


async def test_a_personal_site_without_a_key_pair_or_whose_login_fails_has_no_quote_and_no_sinopac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    without_keys = shioaji_site(ShioajiServer.SIMULATION)
    without_keys.shioaji = ShioajiConfig(
        _env_file=None, **without_keys.shioaji.model_dump(include={"poll_interval_seconds", "max_polls"})
    )

    assert await connect_shioaji(without_keys, process(), CLOCK) == (None, None)

    made: list[FakeShioaji] = []
    refused = ConnectionError("Sinopac is under maintenance")
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: made.append(FakeShioaji(simulation, login_error=refused)) or made[-1])
    shared = process()

    for _ in ("startup", "reload"):
        assert await connect_shioaji(shioaji_site(ShioajiServer.SIMULATION), shared, CLOCK) == (None, None)

    assert [(len(client.logins), client.logouts) for client in made] == [(1, 0), (1, 0)]


def made_clients(monkeypatch: pytest.MonkeyPatch, **fields: object) -> list[FakeShioaji]:
    """Every client a runtime makes from now on, each a FakeShioaji with `fields` and a contract for 2330."""
    made: list[FakeShioaji] = []
    contracts = FakeContracts(FakeStocks({"2330": stock("2330")}))
    monkeypatch.setattr(
        shioaji, "Shioaji", lambda simulation: made.append(FakeShioaji(simulation, Contracts=contracts, **fields)) or made[-1]
    )
    return made


async def test_the_runtimes_of_one_login_pace_their_requests_together(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shioaji counts its 50 market-data queries per 10 seconds per login, whichever runtime asks."""
    made = made_clients(monkeypatch)
    site, shared = shioaji_site(ShioajiServer.SIMULATION), process()
    site.market_data = site.market_data.model_copy(update={"quote_request_interval_seconds": 0.2})
    (startup, _), (reload, _) = [await connect_shioaji(site, shared, CLOCK) for _ in ("startup", "reload")]
    [client] = made
    client.snapshot_answers = {"2330": snapshot("2330", FRIDAY_AFTER_HOURS, 101.5, 10)}
    assert startup is not None and reload is not None
    started = asyncio.get_running_loop().time()

    await asyncio.gather(*(quotes.fetch_realtime_bars([Stock(stock_id="2330")]) for quotes in (startup, reload, startup)))

    assert len(client.snapshot_requests) == 3
    assert asyncio.get_running_loop().time() - started >= 0.4


async def test_a_login_a_timed_out_reload_left_running_is_the_one_the_next_reload_uses(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()
    made = made_clients(monkeypatch, login_gate=gate)
    site, shared = shioaji_site(ShioajiServer.SIMULATION), process()

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.1):
            await connect_shioaji(site, shared, CLOCK)

    gate.set()
    quotes, _ = await connect_shioaji(site, shared, CLOCK)

    assert quotes is not None
    assert [(len(client.logins), client.logouts) for client in made] == [(1, 0)]


SDK_REFUSAL = TokenError(401, "person A123456789 signed in from 203.0.113.7 has no market data")
"""An SDK error that carries what the server answered, the login's person id and an address included."""


async def test_an_sdk_error_reaches_the_logs_and_the_run_record_as_its_type_and_status_only(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = RecordingLogger()
    made_clients(monkeypatch, login_error=SDK_REFUSAL)
    site = shioaji_site(ShioajiServer.SIMULATION)
    shared = ProcessState(logger=logger, attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())
    assert await connect_shioaji(site, shared, CLOCK) == (None, None)

    made_clients(monkeypatch, market_data_error=SDK_REFUSAL)
    quotes, _ = await connect_shioaji(site, process(), CLOCK)
    assert quotes is not None
    stack = await open_stack(tmp_path)
    stack.quotes.fetch_realtime_bars = quotes.fetch_realtime_bars
    status = await stack.pipeline.buy_manually(analysed_stock())

    said = [message for _, message in logger.records] + status.stats.errors
    assert [message for message in said if "TokenError, status 401" in message] == [
        "Shioaji Simulation login failed: TokenError, status 401. No realtime quote, so no order",
        "Failed to fetch realtime market data: Shioaji answered TokenError, status 401",
    ]
    assert not [message for message in said if "A123456789" in message or "203.0.113.7" in message]
