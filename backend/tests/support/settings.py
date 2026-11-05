"""The settings the app ships, for tests that build an adapter, a use case or a runtime themselves."""

from pathlib import Path

from a_domain.types.enums import DatabaseBackend, ExecutionProvider, OrderMode, SystemEnvironment
from b_application.config.app_config import AppConfig, DbConfig
from b_application.config.settings_loader import inject_built_in_strategies, load_yaml, settings_texts
from b_application.config.trading_config import ShioajiConfig, TradingConfig

APPSETTING = Path(__file__).resolve().parents[3] / "config" / "appsetting.yaml"
PLACEHOLDER = "placeholder"
"""The database credentials a test sets: never a real one, and nothing connects with them."""


def shipped_config(project_root: Path = Path(".")) -> AppConfig:
    """
    config/appsetting.yaml with the built-in strategies, as load_settings reads them, without the prompts of
    config/instructions.yaml. A settings value has no code default, so a test reads it from here and changes what it
    needs with model_copy(update=...).
    """
    settings = load_yaml(APPSETTING)
    inject_built_in_strategies(settings, APPSETTING.parent / "strategies", settings_texts(APPSETTING.parents[1]))
    return AppConfig(project_root=project_root, **settings)


def environment_setup(
    config: AppConfig, environment: SystemEnvironment, provider: ExecutionProvider, order_mode: OrderMode
) -> AppConfig:
    """
    `config` in `environment` with that broker and order mode, and exactly the Shioaji credentials the environment
    reads, never another's, each set to its own variable's name, so a test sees which variable reached which part of a
    login; in prod a PostgreSQL database with placeholder credentials, since prod refuses SQLite. Read from the process
    environment only, never .env.
    """
    polling = config.shioaji.model_dump(include={"poll_interval_seconds", "max_polls"})
    credentials = {credential.value: credential.value for credential in environment.shioaji_credentials}
    update = {
        "environment": environment,
        "trading": TradingConfig(execution_provider=provider, order_mode=order_mode),
        "shioaji": ShioajiConfig(_env_file=None, **polling, **credentials),
    }

    if DatabaseBackend.SQLITE not in environment.databases:
        update["db"] = DbConfig(
            _env_file=None,
            backend=DatabaseBackend.POSTGRESQL,
            chroma_persist_path=config.db.chroma_persist_path,
            DB_USER=PLACEHOLDER,
            DB_PASSWORD=PLACEHOLDER,
            DB_HOST="127.0.0.1",
            DB_NAME=PLACEHOLDER,
        )

    return config.model_copy(update=update)
