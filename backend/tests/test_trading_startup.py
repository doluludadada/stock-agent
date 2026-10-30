import io
from itertools import product
from pathlib import Path

import pytest
from rich.console import Console
from shioaji.error import TokenError
from support.fake_shioaji import FakeShioaji
from trading_stack import SilentLogger

import c_infrastructure.trading.shioaji.execution_provider as shioaji_adapter
from a_domain.types.enums import ExecutionProvider, OrderMode, SystemEnvironment
from b_application.schemas.config import AppConfig, ShioajiConfig, TradingConfig
from c_infrastructure.system.config_loader import load_settings
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider
from c_infrastructure.trading.shioaji.execution_provider import ShioajiExecutionProvider
from d_presentation.cli import interactive
from d_presentation.cli.cli_container import TradingSetupError, create_execution_provider, validate_trading_environment

pytestmark = pytest.mark.asyncio

DEV, TEST, LIVE = SystemEnvironment.DEV, SystemEnvironment.TEST, SystemEnvironment.LIVE
MOCK, SHIOAJI = ExecutionProvider.MOCK, ExecutionProvider.SHIOAJI

STARTS = {
    (DEV, MOCK, OrderMode.MOCK_ONLY),
    (DEV, MOCK, OrderMode.DISABLED),
    (TEST, MOCK, OrderMode.MOCK_ONLY),
    (TEST, MOCK, OrderMode.DISABLED),
    (TEST, SHIOAJI, OrderMode.DISABLED),
    (LIVE, MOCK, OrderMode.MOCK_ONLY),
    (LIVE, MOCK, OrderMode.DISABLED),
    (LIVE, SHIOAJI, OrderMode.DISABLED),
    (LIVE, SHIOAJI, OrderMode.LIVE),
}
"""US-009 and US-301: DEV never touches a real broker, mock_only needs the mock, live needs environment live and Shioaji."""

ALL_CREDENTIALS = {
    "SHIOAJI_API_KEY": "key",
    "SHIOAJI_SECRET_KEY": "secret",
    "SHIOAJI_CA_PATH": "/certs/Sinopac.pfx",
    "SHIOAJI_CA_PASSWORD": "ca-password",
    "SHIOAJI_PERSON_ID": "A123456789",
}


def trading_config(
    environment: SystemEnvironment, provider: ExecutionProvider, mode: OrderMode, simulation: bool = True, **credentials: str | None
) -> AppConfig:
    config = AppConfig(project_root=Path("."))
    config.environment = environment
    config.trading = TradingConfig(execution_provider=provider, order_mode=mode)
    config.shioaji = ShioajiConfig(_env_file=None, simulation=simulation, **{**dict.fromkeys(ALL_CREDENTIALS), **credentials})

    return config


@pytest.mark.parametrize(("environment", "provider", "mode"), list(product(SystemEnvironment, ExecutionProvider, OrderMode)))
async def test_each_environment_provider_and_order_mode_either_starts_or_is_refused(
    monkeypatch, environment: SystemEnvironment, provider: ExecutionProvider, mode: OrderMode
) -> None:
    monkeypatch.setattr(shioaji_adapter, "Shioaji", FakeShioaji)
    config = trading_config(environment, provider, mode, **ALL_CREDENTIALS)

    if (environment, provider, mode) not in STARTS:
        with pytest.raises(TradingSetupError):
            validate_trading_environment(config)
        return

    validate_trading_environment(config)
    broker = await create_execution_provider(config, db=None, logger=SilentLogger())

    assert type(broker) is (MockExecutionProvider if provider == MOCK else ShioajiExecutionProvider)


@pytest.mark.parametrize(
    ("simulation", "credentials", "missing"),
    [
        (True, {}, "SHIOAJI_API_KEY, SHIOAJI_SECRET_KEY"),
        (True, {"SHIOAJI_API_KEY": "key", "SHIOAJI_SECRET_KEY": "   "}, "SHIOAJI_SECRET_KEY"),
        (False, {"SHIOAJI_API_KEY": "key", "SHIOAJI_SECRET_KEY": "secret"}, "SHIOAJI_CA_PATH, SHIOAJI_CA_PASSWORD, SHIOAJI_PERSON_ID"),
    ],
)
async def test_shioaji_without_its_credentials_refuses_to_start_and_names_them(
    simulation: bool, credentials: dict[str, str], missing: str
) -> None:
    config = trading_config(LIVE, SHIOAJI, OrderMode.LIVE, simulation=simulation, **credentials)

    with pytest.raises(TradingSetupError, match=f"execution_provider shioaji needs {missing} in the environment or .env"):
        validate_trading_environment(config)


async def test_simulation_starts_without_a_ca_certificate(monkeypatch) -> None:
    monkeypatch.setattr(shioaji_adapter, "Shioaji", FakeShioaji)
    config = trading_config(LIVE, SHIOAJI, OrderMode.LIVE, SHIOAJI_API_KEY="key", SHIOAJI_SECRET_KEY="secret")

    validate_trading_environment(config)

    assert type(await create_execution_provider(config, db=None, logger=SilentLogger())) is ShioajiExecutionProvider


async def test_a_failed_shioaji_login_stops_startup_with_the_broker_reason(monkeypatch) -> None:
    monkeypatch.setattr(
        shioaji_adapter, "Shioaji", lambda simulation: FakeShioaji(simulation, login_error=TokenError(401, "bad api key"))
    )
    config = trading_config(LIVE, SHIOAJI, OrderMode.LIVE, simulation=False, **ALL_CREDENTIALS)

    with pytest.raises(TradingSetupError, match="Shioaji production login failed: TokenError: StatusCode: 401, Detail: bad api key"):
        await create_execution_provider(config, db=None, logger=SilentLogger())


async def test_the_mock_broker_in_mock_only_mode_is_the_default() -> None:
    shipped = load_settings()

    assert (AppConfig(project_root=Path(".")).trading, shipped.trading) == (
        TradingConfig(execution_provider=MOCK, order_mode=OrderMode.MOCK_ONLY),
        TradingConfig(execution_provider=MOCK, order_mode=OrderMode.MOCK_ONLY),
    )
    assert (ShioajiConfig(_env_file=None).simulation, shipped.shioaji.simulation) == (True, True)


@pytest.fixture
def screen(monkeypatch) -> io.StringIO:
    output = io.StringIO()
    monkeypatch.setattr(interactive, "console", Console(file=output, width=200))
    return output


@pytest.mark.parametrize(
    ("simulation", "mode", "server", "orders"),
    [
        (
            True,
            OrderMode.LIVE,
            "SHIOAJI SIMULATION (paper trading)",
            "Orders LIVE: menus 2 and 3 and a confirmed manual BUY send orders",
        ),
        (False, OrderMode.LIVE, "SHIOAJI PRODUCTION: REAL ACCOUNT, REAL MONEY", "Orders LIVE: menus 2 and 3"),
        (False, OrderMode.DISABLED, "SHIOAJI PRODUCTION: REAL ACCOUNT, REAL MONEY", "Orders DISABLED: no order is sent"),
    ],
)
async def test_the_menu_header_warns_about_a_real_broker(
    screen: io.StringIO, simulation: bool, mode: OrderMode, server: str, orders: str
) -> None:
    interactive.print_menu(trading_config(LIVE, SHIOAJI, mode, simulation=simulation, **ALL_CREDENTIALS))

    output = screen.getvalue()
    assert "REAL BROKER" in output and server in output and orders in output
    assert "Execution Provider: SHIOAJI" in output and f"Orders:             {mode.value.upper()}" in output


async def test_the_menu_header_shows_no_broker_warning_for_the_mock(screen: io.StringIO) -> None:
    interactive.print_menu(trading_config(DEV, MOCK, OrderMode.MOCK_ONLY))

    output = screen.getvalue()
    assert "REAL BROKER" not in output
    assert "Execution Provider: MOCK" in output and "Account:            mock-dev" in output


async def test_only_shioaji_simulation_in_the_environment_can_turn_simulation_off(monkeypatch) -> None:
    monkeypatch.setenv("SIMULATION", "false")
    unrelated = ShioajiConfig(_env_file=None).simulation
    monkeypatch.setenv("SHIOAJI_SIMULATION", "false")

    assert (unrelated, ShioajiConfig(_env_file=None).simulation) == (True, False)
