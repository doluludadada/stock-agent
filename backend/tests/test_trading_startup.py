import asyncio
import io
from pathlib import Path
from typing import get_args

import pytest
import shioaji
from pydantic import BaseModel
from rich.console import Console
from shioaji.error import TokenError
from support.fake_shioaji import FakeShioaji
from support.fakes import RecordingLogger
from support.harness import build_harness, harness_config
from support.settings import environment_setup, shipped_config
from trading_stack import SilentLogger

from a_domain.rules.trading.order_rule import BrokerLink
from a_domain.types.enums import DatabaseBackend, ExecutionProvider, ShioajiCredential, SystemEnvironment
from b_application.config.app_config import AppConfig
from b_application.config.market_data_config import MarketHoursConfig
from b_application.config.settings_loader import validate_trading_environment
from b_application.config.trading_config import ShioajiConfig, TradingConfig
from c_infrastructure.system.attempt_log import MemoryAttemptLog
from c_infrastructure.system.market_clock import TaiwanMarketClock
from c_infrastructure.trading.shioaji.execution_provider import ShioajiExecutionProvider
from d_presentation.cli import interactive, terminal
from d_presentation.dependencies import ProcessState, TradingSetupError, connect_shioaji, get_project_root, load_settings

pytestmark = pytest.mark.asyncio


def process() -> ProcessState:
    return ProcessState(logger=SilentLogger(), attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())


DEV, TEST, PROD = SystemEnvironment.DEV, SystemEnvironment.TEST, SystemEnvironment.PROD

PRODUCTION = [credential.value for credential in PROD.shioaji_credentials]
SECRET = "Kq7x9"
"""A credential's value a refusal must never show."""


def trading_config(environment: SystemEnvironment) -> AppConfig:
    """The shipped settings in the environment, with placeholders for exactly the Shioaji credentials it reads."""
    return environment_setup(shipped_config(), environment)


def without(config: AppConfig, *credentials: ShioajiCredential) -> AppConfig:
    polling = config.shioaji.model_dump(include={"poll_interval_seconds", "max_polls"})
    kept = {credential.value: credential.value for credential in config.shioaji.given() if credential not in credentials}
    return config.model_copy(update={"shioaji": ShioajiConfig(_env_file=None, **polling, **kept)})


@pytest.mark.parametrize("environment", list(SystemEnvironment))
async def test_every_environment_starts_and_offers_sinopac_on_the_server_it_trades_on(
    monkeypatch, environment: SystemEnvironment
) -> None:
    monkeypatch.setattr(shioaji, "Shioaji", FakeShioaji)
    config = trading_config(environment)
    validate_trading_environment(config)

    quotes, broker = await connect_shioaji(config, process(), TaiwanMarketClock(MarketHoursConfig()))

    assert quotes is not None and type(broker) is ShioajiExecutionProvider
    assert broker.link() == BrokerLink(broker=ExecutionProvider.SHIOAJI, up=True, simulation=environment.shioaji_simulation)


async def test_prod_without_its_certificate_keeps_the_quotes_and_offers_no_sinopac_naming_what_failed(monkeypatch) -> None:
    monkeypatch.setattr(shioaji, "Shioaji", FakeShioaji)
    removed = (ShioajiCredential.CA_PATH, ShioajiCredential.CA_PASSWORD, ShioajiCredential.PERSON_ID)
    logger = RecordingLogger()
    state = ProcessState(logger=logger, attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())

    quotes, broker = await connect_shioaji(without(trading_config(PROD), *removed), state, TaiwanMarketClock(MarketHoursConfig()))

    assert quotes is not None and broker is None
    assert any(
        "SinoPac production orders unavailable: Shioaji production needs the CA certificate" in line for _, line in logger.records
    )


async def test_a_site_without_the_key_pair_has_no_quote_and_offers_no_sinopac() -> None:
    config = without(trading_config(TEST), *TEST.shioaji_credentials)
    validate_trading_environment(config)

    assert await connect_shioaji(config, process(), TaiwanMarketClock(MarketHoursConfig())) == (None, None)


@pytest.mark.parametrize("environment", [DEV, TEST])
@pytest.mark.parametrize("credential", PRODUCTION)
async def test_dev_and_test_refuse_to_start_while_a_production_credential_is_in_the_environment(
    environment: SystemEnvironment, credential: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(credential, SECRET)
    config = trading_config(environment)
    config.shioaji = ShioajiConfig(_env_file=None, **config.shioaji.model_dump(include={"poll_interval_seconds", "max_polls"}))

    with pytest.raises(TradingSetupError) as refused:
        validate_trading_environment(config)

    assert f"environment {environment.value} refuses to start while {credential} is set" in str(refused.value)
    assert SECRET not in str(refused.value)


async def test_a_production_credential_in_dot_env_stops_a_test_machine_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(f'SHIOAJI_CA_PASSWORD="{SECRET}"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    config = trading_config(TEST)
    config.shioaji = ShioajiConfig(**config.shioaji.model_dump(include={"poll_interval_seconds", "max_polls"}))

    with pytest.raises(TradingSetupError, match="environment test refuses to start while SHIOAJI_CA_PASSWORD is set") as refused:
        validate_trading_environment(config)

    assert SECRET not in str(refused.value)


async def test_dev_and_test_machines_with_only_the_test_pair_start(monkeypatch: pytest.MonkeyPatch) -> None:
    for credential in TEST.shioaji_credentials:
        monkeypatch.setenv(credential.value, SECRET)

    for environment in (DEV, TEST):
        validate_trading_environment(trading_config(environment))


async def test_the_test_environment_logs_in_to_simulation_with_only_the_test_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    clients: list[FakeShioaji] = []
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: clients.append(FakeShioaji(simulation)) or clients[-1])

    await connect_shioaji(trading_config(TEST), process(), TaiwanMarketClock(MarketHoursConfig()))

    [client] = clients
    assert (client.simulation, client.ca_activations) == (True, [])
    assert client.logins == [{"api_key": "SHIOAJI_API_KEY_TEST", "secret_key": "SHIOAJI_SECRET_KEY_TEST", "subscribe_trade": False}]


async def test_prod_never_logs_in_to_simulation_and_activates_its_certificate(monkeypatch: pytest.MonkeyPatch) -> None:
    clients: list[FakeShioaji] = []
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: clients.append(FakeShioaji(simulation)) or clients[-1])

    await connect_shioaji(trading_config(PROD), process(), TaiwanMarketClock(MarketHoursConfig()))

    [client] = clients
    assert client.simulation is False
    assert client.logins == [{"api_key": "SHIOAJI_API_KEY", "secret_key": "SHIOAJI_SECRET_KEY", "subscribe_trade": False}]
    assert client.ca_activations == [
        {"ca_path": "SHIOAJI_CA_PATH", "ca_passwd": "SHIOAJI_CA_PASSWORD", "person_id": "SHIOAJI_PERSON_ID"}
    ]


async def test_prod_refuses_sqlite() -> None:
    config = trading_config(PROD).model_copy(update={"db": shipped_config().db})

    assert config.db.backend == DatabaseBackend.SQLITE
    with pytest.raises(TradingSetupError, match="environment prod needs db.backend postgresql, not sqlite"):
        validate_trading_environment(config)


async def test_no_setting_or_variable_chooses_simulation_only_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIOAJI_SIMULATION", "false")
    monkeypatch.setenv("SIMULATION", "true")
    credentials = trading_config(PROD).shioaji.model_copy(
        update=trading_config(TEST).shioaji.model_dump(include={"api_key_test", "secret_key_test"})
    )

    assert (credentials.login(TEST).simulation, credentials.login(PROD).simulation) == (True, False)


async def test_a_failed_shioaji_login_leaves_no_quote_and_no_sinopac_saying_why_without_the_servers_words(monkeypatch) -> None:
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: FakeShioaji(simulation, login_error=TokenError(401, "bad api key")))
    logger = RecordingLogger()
    state = ProcessState(logger=logger, attempt_log=MemoryAttemptLog(), cache_writes=asyncio.Lock())

    assert await connect_shioaji(trading_config(PROD), state, TaiwanMarketClock(MarketHoursConfig())) == (None, None)
    assert any(line.startswith("Shioaji production login failed: TokenError, status 401.") for _, line in logger.records)
    assert not any("bad api key" in line for _, line in logger.records)


async def test_the_shipped_settings_are_dev_with_the_owners_sinopac_limits() -> None:
    shipped = load_settings(get_project_root())

    assert (shipped.environment, shipped.trading) == (DEV, TradingConfig(max_order_value=100_000, max_daily_buy_value=300_000))


@pytest.fixture
def screen(monkeypatch) -> io.StringIO:
    output = io.StringIO()
    monkeypatch.setattr(terminal, "console", Console(file=output, width=200))
    return output


@pytest.mark.parametrize(
    ("environment", "orders"),
    [
        (DEV, "your mock account, or SinoPac (simulation) when you choose it for a run"),
        (PROD, "your mock account, or SinoPac (PRODUCTION, REAL MONEY) when you choose it for a run"),
    ],
)
async def test_the_menu_header_names_sinopac_and_its_server_where_the_administrator_may_choose_it(
    screen: io.StringIO, environment: SystemEnvironment, orders: str
) -> None:
    harness = build_harness(config=environment_setup(harness_config(), environment), sinopac=True)

    interactive.print_menu(harness.runtime, harness.session())

    assert f"Orders:             {orders}" in screen.getvalue()


async def test_the_menu_header_names_only_the_mock_account_without_sinopac(screen: io.StringIO) -> None:
    harness = build_harness()

    interactive.print_menu(harness.runtime, harness.session())

    assert "Orders:             your mock account\n" in screen.getvalue()


def menu_entry(output: str, title: str) -> list[str]:
    lines = output.splitlines()
    start = lines.index(title)
    return [line.strip() for line in lines[start + 1 : lines.index("", start)]]


async def test_menus_2_3_and_4_say_their_orders_go_to_the_account_the_run_starts_on(screen: io.StringIO) -> None:
    harness = build_harness(sinopac=True)

    interactive.print_menu(harness.runtime, harness.session())

    output, orders = (
        screen.getvalue(),
        "May submit orders to the account the run starts on: your mock account unless you choose another.",
    )
    assert orders in menu_entry(output, "[2] Scan Social Buzz")
    assert orders in menu_entry(output, "[3] Run Intraday Trading")
    assert orders in menu_entry(output, "[4] Analyse Specific Stocks"), "a confirmed manual BUY sends an order"
    assert not any("submit orders" in line for line in menu_entry(output, "[1] Run Full Cycle"))


BOOLEAN_SETTINGS = {
    "accounts.registration_open",
    "behavior.enable_web_search",
    "behavior.enable_x_search",
    "behavior.enable_inline_citations",
    "notifications.enabled",
    "sources.exchange.daily_reports.index_volume_lots",
}
"""
None of them sends or stops an order: open registration, the AI's web search, X search and inline citations, LINE
notifications, and whether an exchange's index report counts its volume in lots.
"""


def boolean_settings(model: type[BaseModel], prefix: str = "") -> set[str]:
    found: set[str] = set()

    for name, field in model.model_fields.items():
        for annotation in (field.annotation, *get_args(field.annotation)):
            if annotation is bool:
                found.add(prefix + name)
            elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
                found |= boolean_settings(annotation, f"{prefix}{name}.")

    return found


async def test_no_setting_turns_orders_on_or_off() -> None:
    assert boolean_settings(AppConfig) == BOOLEAN_SETTINGS, (
        "A run's own broker choice and the order gates decide where an order goes. A new boolean setting must not "
        "switch orders on or off: list it here only if it switches something else."
    )
