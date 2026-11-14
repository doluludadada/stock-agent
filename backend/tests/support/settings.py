"""The settings the app ships, for tests that build an adapter, a use case or a runtime themselves."""

from pathlib import Path

from a_domain.types.enums import SystemEnvironment
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import inject_built_in_strategies, load_yaml, settings_texts
from b_application.config.trading_config import ShioajiConfig

APPSETTING = Path(__file__).resolve().parents[3] / "config" / "appsetting.yaml"


def shipped_config(project_root: Path = Path(".")) -> AppConfig:
    """
    config/appsetting.yaml with the built-in strategies, as load_settings reads them, without the prompts of
    config/instructions.yaml. A settings value has no code default, so a test reads it from here and changes what it
    needs with model_copy(update=...).
    """
    settings = load_yaml(APPSETTING)
    inject_built_in_strategies(settings, APPSETTING.parent / "strategies", settings_texts(APPSETTING.parents[1]))
    return AppConfig(project_root=project_root, **settings)


def environment_setup(config: AppConfig, environment: SystemEnvironment) -> AppConfig:
    """
    `config` in `environment` with exactly the Shioaji credentials the environment reads, never another's, each set to
    its own variable's name, so a test sees which variable reached which part of a login. Read from the process
    environment only, never .env.
    """
    polling = config.shioaji.model_dump(include={"poll_interval_seconds", "max_polls"})
    credentials = {credential.value: credential.value for credential in environment.shioaji_credentials}
    return config.model_copy(update={"environment": environment, "shioaji": ShioajiConfig(_env_file=None, **polling, **credentials)})
