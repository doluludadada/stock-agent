"""The settings the app ships, for tests that build an adapter, a use case or a runtime themselves."""

from pathlib import Path

from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import inject_built_in_strategies, load_yaml

APPSETTING = Path(__file__).resolve().parents[3] / "config" / "appsetting.yaml"


def shipped_config(project_root: Path = Path(".")) -> AppConfig:
    """
    config/appsetting.yaml with the built-in strategies, as load_settings reads them, without the prompts of
    config/instructions.yaml. A settings value has no code default, so a test reads it from here and changes what it
    needs with model_copy(update=...).
    """
    settings = load_yaml(APPSETTING)
    inject_built_in_strategies(settings, APPSETTING.parent / "strategies")
    return AppConfig(project_root=project_root, **settings)
