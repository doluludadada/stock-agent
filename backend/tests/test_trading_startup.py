import io
from itertools import product
from pathlib import Path
from typing import get_args

import pytest
import shioaji
from pydantic import BaseModel
from rich.console import Console
from shioaji.error import TokenError
from support.fake_shioaji import FakeShioaji
from support.harness import build_harness
from support.settings import environment_setup, shipped_config
from trading_stack import SilentLogger

from a_domain.types.enums import DatabaseBackend, ExecutionProvider, OrderMode, ShioajiCredential, SystemEnvironment
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import validate_trading_environment
from b_application.config.trading_config import ShioajiConfig, TradingConfig
from c_infrastructure.trading.shioaji.execution_provider import ShioajiExecutionProvider
from d_presentation.cli import interactive, terminal
from d_presentation.dependencies import TradingSetupError, get_project_root, load_settings, open_real_broker

pytestmark = pytest.mark.asyncio

DEV, TEST, PROD = SystemEnvironment.DEV, SystemEnvironment.TEST, SystemEnvironment.PROD
MOCK, SHIOAJI = ExecutionProvider.MOCK, ExecutionProvider.SHIOAJI

STARTS = {
    (DEV, MOCK, OrderMode.MOCK_ONLY),
    (DEV, MOCK, OrderMode.DISABLED),
    (TEST, MOCK, OrderMode.MOCK_ONLY),
    (TEST, MOCK, OrderMode.DISABLED),
    (TEST, SHIOAJI, OrderMode.DISABLED),
    (PROD, MOCK, OrderMode.MOCK_ONLY),
    (PROD, MOCK, OrderMode.DISABLED),
    (PROD, SHIOAJI, OrderMode.DISABLED),
    (PROD, SHIOAJI, OrderMode.LIVE),
}
"""Dev never touches a real broker, mock_only needs the mock, live needs environment prod and Shioaji."""

PRODUCTION = [credential.value for credential in PROD.shioaji_credentials]
SECRET = "Kq7x9"
"""A credential's value a refusal must never show."""


def trading_config(environment: SystemEnvironment, provider: ExecutionProvider, mode: OrderMode) -> AppConfig:
    """The shipped settings in the environment, with placeholders for exactly the Shioaji credentials it reads."""
    return environment_setup(shipped_config(), environment, provider, mode)


def without(config: AppConfig, *credentials: ShioajiCredential) -> AppConfig:
    polling = config.shioaji.model_dump(include={"poll_interval_seconds", "max_polls"})
    kept = {credential.value: credential.value for credential in config.shioaji.given() if credential not in credentials}
    return config.model_copy(update={"shioaji": ShioajiConfig(_env_file=None, **polling, **kept)})


@pytest.mark.parametrize(("environment", "provider", "mode"), list(product(SystemEnvironment, ExecutionProvider, OrderMode)))
async def test_each_environment_provider_and_order_mode_either_starts_or_is_refused(
    monkeypatch, environment: SystemEnvironment, provider: ExecutionProvider, mode: OrderMode
) -> None:
    monkeypatch.setattr(shioaji, "Shioaji", FakeShioaji)
    config = trading_config(environment, provider, mode)

    if (environment, provider, mode) not in STARTS:
        with pytest.raises(TradingSetupError):
            validate_trading_environment(config)
        return

    validate_trading_environment(config)

    async with open_real_broker(config, logger=SilentLogger()) as broker:
        assert (broker is None) if provider == MOCK else type(broker) is ShioajiExecutionProvider


@pytest.mark.parametrize(
    ("environment", "removed", "missing"),
    [
        (TEST, TEST.shioaji_credentials, "SHIOAJI_API_KEY_TEST, SHIOAJI_SECRET_KEY_TEST"),
        (PROD, (ShioajiCredential.SECRET_KEY,), "SHIOAJI_SECRET_KEY"),
        (
            PROD,
            (ShioajiCredential.CA_PATH, ShioajiCredential.CA_PASSWORD, ShioajiCredential.PERSON_ID),
            "SHIOAJI_CA_PATH, SHIOAJI_CA_PASSWORD, SHIOAJI_PERSON_ID",
        ),
    ],
)
async def test_shioaji_without_the_credentials_of_its_environment_refuses_to_start_and_names_them(
    environment: SystemEnvironment, removed: tuple[ShioajiCredential, ...], missing: str
) -> None:
    config = without(trading_config(environment, SHIOAJI, OrderMode.DISABLED), *removed)

    with pytest.raises(
        TradingSetupError, match=f"shioaji in environment {environment.value} needs {missing} in the environment or .env"
    ):
        validate_trading_environment(config)


@pytest.mark.parametrize("environment", [DEV, TEST])
@pytest.mark.parametrize("credential", PRODUCTION)
async def test_dev_and_test_refuse_to_start_while_a_production_credential_is_in_the_environment(
    environment: SystemEnvironment, credential: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(credential, SECRET)
    config = trading_config(environment, MOCK, OrderMode.MOCK_ONLY)
    config.shioaji = ShioajiConfig(_env_file=None, **config.shioaji.model_dump(include={"poll_interval_seconds", "max_polls"}))

    with pytest.raises(TradingSetupError) as refused:
        validate_trading_environment(config)

    assert f"environment {environment.value} refuses to start while {credential} is set" in str(refused.value)
    assert SECRET not in str(refused.value)


async def test_a_production_credential_in_dot_env_stops_a_test_machine_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(f'SHIOAJI_CA_PASSWORD="{SECRET}"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    config = trading_config(TEST, MOCK, OrderMode.MOCK_ONLY)
    config.shioaji = ShioajiConfig(**config.shioaji.model_dump(include={"poll_interval_seconds", "max_polls"}))

    with pytest.raises(TradingSetupError, match="environment test refuses to start while SHIOAJI_CA_PASSWORD is set") as refused:
        validate_trading_environment(config)

    assert SECRET not in str(refused.value)


async def test_a_test_machine_with_only_the_test_pair_starts_and_ignores_it_on_the_mock_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for credential in TEST.shioaji_credentials:
        monkeypatch.setenv(credential.value, SECRET)

    for environment in (DEV, TEST):
        validate_trading_environment(trading_config(environment, MOCK, OrderMode.MOCK_ONLY))


async def test_the_test_environment_logs_in_to_simulation_with_only_the_test_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    clients: list[FakeShioaji] = []
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: clients.append(FakeShioaji(simulation)) or clients[-1])

    async with open_real_broker(trading_config(TEST, SHIOAJI, OrderMode.DISABLED), logger=SilentLogger()):
        pass

    [client] = clients
    assert (client.simulation, client.ca_activations) == (True, [])
    assert client.logins == [{"api_key": "SHIOAJI_API_KEY_TEST", "secret_key": "SHIOAJI_SECRET_KEY_TEST", "subscribe_trade": False}]


async def test_prod_never_logs_in_to_simulation_and_activates_its_certificate(monkeypatch: pytest.MonkeyPatch) -> None:
    clients: list[FakeShioaji] = []
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: clients.append(FakeShioaji(simulation)) or clients[-1])

    async with open_real_broker(trading_config(PROD, SHIOAJI, OrderMode.LIVE), logger=SilentLogger()):
        pass

    [client] = clients
    assert client.simulation is False
    assert client.logins == [{"api_key": "SHIOAJI_API_KEY", "secret_key": "SHIOAJI_SECRET_KEY", "subscribe_trade": False}]
    assert client.ca_activations == [
        {"ca_path": "SHIOAJI_CA_PATH", "ca_passwd": "SHIOAJI_CA_PASSWORD", "person_id": "SHIOAJI_PERSON_ID"}
    ]


@pytest.mark.parametrize(("environment", "provider"), [(DEV, MOCK), (TEST, SHIOAJI)])
async def test_order_mode_live_outside_prod_is_refused_naming_prod(
    environment: SystemEnvironment, provider: ExecutionProvider
) -> None:
    with pytest.raises(TradingSetupError, match=f"order_mode live needs environment prod, not {environment.value}"):
        validate_trading_environment(trading_config(environment, provider, OrderMode.LIVE))


@pytest.mark.parametrize("mode", [OrderMode.MOCK_ONLY, OrderMode.DISABLED])
async def test_prod_refuses_sqlite(mode: OrderMode) -> None:
    config = trading_config(PROD, MOCK, mode).model_copy(update={"db": shipped_config().db})

    assert config.db.backend == DatabaseBackend.SQLITE
    with pytest.raises(TradingSetupError, match="environment prod needs db.backend postgresql, not sqlite"):
        validate_trading_environment(config)


async def test_no_setting_or_variable_chooses_simulation_only_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIOAJI_SIMULATION", "false")
    monkeypatch.setenv("SIMULATION", "true")
    credentials = trading_config(PROD, SHIOAJI, OrderMode.LIVE).shioaji.model_copy(
        update=trading_config(TEST, SHIOAJI, OrderMode.DISABLED).shioaji.model_dump(include={"api_key_test", "secret_key_test"})
    )

    assert (credentials.login(TEST).simulation, credentials.login(PROD).simulation) == (True, False)


async def test_a_failed_shioaji_login_stops_startup_with_the_broker_reason(monkeypatch) -> None:
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: FakeShioaji(simulation, login_error=TokenError(401, "bad api key")))
    config = trading_config(PROD, SHIOAJI, OrderMode.LIVE)

    with pytest.raises(TradingSetupError, match="Shioaji production login failed: TokenError: StatusCode: 401, Detail: bad api key"):
        async with open_real_broker(config, logger=SilentLogger()):
            pass


async def test_the_mock_broker_in_mock_only_mode_on_dev_is_the_default() -> None:
    shipped = load_settings(get_project_root())

    assert (TradingConfig(), shipped.trading) == (
        TradingConfig(execution_provider=MOCK, order_mode=OrderMode.MOCK_ONLY),
        TradingConfig(execution_provider=MOCK, order_mode=OrderMode.MOCK_ONLY),
    )
    assert shipped.environment == DEV


@pytest.fixture
def screen(monkeypatch) -> io.StringIO:
    output = io.StringIO()
    monkeypatch.setattr(terminal, "console", Console(file=output, width=200))
    return output


@pytest.mark.parametrize(
    ("environment", "mode", "server", "orders"),
    [
        (TEST, OrderMode.DISABLED, "SHIOAJI SIMULATION (paper trading)", "Orders DISABLED: no order is sent"),
        (PROD, OrderMode.LIVE, "SHIOAJI PRODUCTION: REAL ACCOUNT, REAL MONEY", "Orders LIVE: menus 2, 3, 4 send orders to the broker"),
        (PROD, OrderMode.DISABLED, "SHIOAJI PRODUCTION: REAL ACCOUNT, REAL MONEY", "Orders DISABLED: no order is sent"),
    ],
)
async def test_the_menu_header_warns_about_a_real_broker(
    screen: io.StringIO, environment: SystemEnvironment, mode: OrderMode, server: str, orders: str
) -> None:
    interactive.print_menu(trading_config(environment, SHIOAJI, mode), build_harness().session())

    output = screen.getvalue()
    assert "REAL BROKER" in output and server in output and orders in output
    assert "Execution Provider: SHIOAJI" in output and f"Orders:             {mode.value.upper()}" in output


async def test_the_menu_header_shows_no_broker_warning_for_the_mock(screen: io.StringIO) -> None:
    interactive.print_menu(trading_config(DEV, MOCK, OrderMode.MOCK_ONLY), build_harness().session())

    output = screen.getvalue()
    assert "REAL BROKER" not in output
    assert "Execution Provider: MOCK" in output and "Account:            your mock account" in output


def menu_entry(output: str, title: str) -> list[str]:
    lines = output.splitlines()
    start = lines.index(title)
    return [line.strip() for line in lines[start + 1 : lines.index("", start)]]


@pytest.mark.parametrize(
    ("environment", "provider", "mode", "orders"),
    [
        (DEV, MOCK, OrderMode.MOCK_ONLY, "May submit orders to the mock broker (order mode MOCK ONLY)."),
        (TEST, MOCK, OrderMode.DISABLED, "Would submit orders, but order mode DISABLED records each one REJECTED and sends none."),
        (PROD, SHIOAJI, OrderMode.LIVE, "May submit orders to the SHIOAJI broker (order mode LIVE)."),
    ],
)
async def test_menus_2_3_and_4_say_they_may_submit_orders_under_the_current_order_mode(
    screen: io.StringIO, environment: SystemEnvironment, provider: ExecutionProvider, mode: OrderMode, orders: str
) -> None:
    interactive.print_menu(trading_config(environment, provider, mode), build_harness().session())

    output = screen.getvalue()
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
}
"""
None of them sends or stops an order: open registration, the AI's web search, X search and inline citations, LINE
notifications.
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


async def test_the_order_mode_is_the_only_setting_that_turns_orders_on_or_off() -> None:
    assert boolean_settings(AppConfig) == BOOLEAN_SETTINGS, (
        "trading.order_mode alone decides whether a workflow may send an order. A new boolean setting must not "
        "duplicate it: add an OrderMode value instead, or list the setting here if it switches something else."
    )
