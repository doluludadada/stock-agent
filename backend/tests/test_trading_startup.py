import io
from itertools import product
from typing import get_args

import pytest
import shioaji
from pydantic import BaseModel
from rich.console import Console
from shioaji.error import TokenError
from support.fake_shioaji import FakeShioaji
from support.settings import shipped_config
from trading_stack import SilentLogger

from a_domain.types.enums import ExecutionProvider, OrderMode, SystemEnvironment
from b_application.config.app_config import AppConfig
from b_application.config.trading_config import ShioajiConfig, TradingConfig
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider
from c_infrastructure.trading.shioaji.execution_provider import ShioajiExecutionProvider
from d_presentation.cli import interactive, terminal
from d_presentation.dependencies import TradingSetupError, create_execution_provider, load_settings, validate_trading_environment

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
"""DEV never touches a real broker, mock_only needs the mock, live needs environment live and Shioaji."""

ALL_CREDENTIALS = {
    "SHIOAJI_API_KEY": "key",
    "SHIOAJI_SECRET_KEY": "secret",
    "SHIOAJI_CA_PATH": "/certs/Sinopac.pfx",
    "SHIOAJI_CA_PASSWORD": "ca-password",
    "SHIOAJI_PERSON_ID": "A123456789",
}


SHIOAJI_POLLING = shipped_config().shioaji.model_dump(include={"poll_interval_seconds", "max_polls"})


def shioaji_from_environment(**values: object) -> ShioajiConfig:
    """A Shioaji section read from the process environment, not .env, with the shipped order polling."""
    return ShioajiConfig(_env_file=None, **SHIOAJI_POLLING, **values)


def trading_config(
    environment: SystemEnvironment, provider: ExecutionProvider, mode: OrderMode, simulation: bool = True, **credentials: str | None
) -> AppConfig:
    config = shipped_config()
    config.environment = environment
    config.trading = TradingConfig(execution_provider=provider, order_mode=mode)
    config.shioaji = shioaji_from_environment(simulation=simulation, **{**dict.fromkeys(ALL_CREDENTIALS), **credentials})

    return config


@pytest.mark.parametrize(("environment", "provider", "mode"), list(product(SystemEnvironment, ExecutionProvider, OrderMode)))
async def test_each_environment_provider_and_order_mode_either_starts_or_is_refused(
    monkeypatch, environment: SystemEnvironment, provider: ExecutionProvider, mode: OrderMode
) -> None:
    monkeypatch.setattr(shioaji, "Shioaji", FakeShioaji)
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
    monkeypatch.setattr(shioaji, "Shioaji", FakeShioaji)
    config = trading_config(LIVE, SHIOAJI, OrderMode.LIVE, SHIOAJI_API_KEY="key", SHIOAJI_SECRET_KEY="secret")

    validate_trading_environment(config)

    assert type(await create_execution_provider(config, db=None, logger=SilentLogger())) is ShioajiExecutionProvider


async def test_a_failed_shioaji_login_stops_startup_with_the_broker_reason(monkeypatch) -> None:
    monkeypatch.setattr(shioaji, "Shioaji", lambda simulation: FakeShioaji(simulation, login_error=TokenError(401, "bad api key")))
    config = trading_config(LIVE, SHIOAJI, OrderMode.LIVE, simulation=False, **ALL_CREDENTIALS)

    with pytest.raises(TradingSetupError, match="Shioaji production login failed: TokenError: StatusCode: 401, Detail: bad api key"):
        await create_execution_provider(config, db=None, logger=SilentLogger())


async def test_the_mock_broker_in_mock_only_mode_is_the_default() -> None:
    shipped = load_settings()

    assert (TradingConfig(), shipped.trading) == (
        TradingConfig(execution_provider=MOCK, order_mode=OrderMode.MOCK_ONLY),
        TradingConfig(execution_provider=MOCK, order_mode=OrderMode.MOCK_ONLY),
    )
    assert (shioaji_from_environment().simulation, shipped.shioaji.simulation) == (True, True)


@pytest.fixture
def screen(monkeypatch) -> io.StringIO:
    output = io.StringIO()
    monkeypatch.setattr(terminal, "console", Console(file=output, width=200))
    return output


@pytest.mark.parametrize(
    ("simulation", "mode", "server", "orders"),
    [
        (True, OrderMode.LIVE, "SHIOAJI SIMULATION (paper trading)", "Orders LIVE: menus 2, 3, 4 send orders to the broker"),
        (
            False,
            OrderMode.LIVE,
            "SHIOAJI PRODUCTION: REAL ACCOUNT, REAL MONEY",
            "Orders LIVE: menus 2, 3, 4 send orders to the broker",
        ),
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


def menu_entry(output: str, title: str) -> list[str]:
    lines = output.splitlines()
    start = lines.index(title)
    return [line.strip() for line in lines[start + 1 : lines.index("", start)]]


@pytest.mark.parametrize(
    ("environment", "provider", "mode", "orders"),
    [
        (DEV, MOCK, OrderMode.MOCK_ONLY, "May submit orders to the mock broker (order mode MOCK ONLY)."),
        (TEST, MOCK, OrderMode.DISABLED, "Would submit orders, but order mode DISABLED records each one REJECTED and sends none."),
        (LIVE, SHIOAJI, OrderMode.LIVE, "May submit orders to the SHIOAJI broker (order mode LIVE)."),
    ],
)
async def test_menus_2_3_and_4_say_they_may_submit_orders_under_the_current_order_mode(
    screen: io.StringIO, environment: SystemEnvironment, provider: ExecutionProvider, mode: OrderMode, orders: str
) -> None:
    interactive.print_menu(trading_config(environment, provider, mode, **ALL_CREDENTIALS))

    output = screen.getvalue()
    assert orders in menu_entry(output, "[2] Scan Social Buzz")
    assert orders in menu_entry(output, "[3] Run Intraday Trading")
    assert orders in menu_entry(output, "[4] Analyse Specific Stocks"), "a confirmed manual BUY sends an order"
    assert not any("submit orders" in line for line in menu_entry(output, "[1] Run Full Cycle"))


async def test_only_shioaji_simulation_in_the_environment_can_turn_simulation_off(monkeypatch) -> None:
    monkeypatch.setenv("SIMULATION", "false")
    unrelated = shioaji_from_environment().simulation
    monkeypatch.setenv("SHIOAJI_SIMULATION", "false")

    assert (unrelated, shioaji_from_environment().simulation) == (True, False)


BOOLEAN_SETTINGS = {
    "behavior.enable_web_search",
    "behavior.enable_x_search",
    "behavior.enable_inline_citations",
    "notifications.enabled",
    "shioaji.simulation",
}
"""None of them sends or stops an order: the AI's web search, X search and inline citations, LINE notifications, Shioaji's server."""


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
