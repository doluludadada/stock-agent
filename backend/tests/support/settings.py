"""The settings the app ships, for tests that build an adapter, a use case or a runtime themselves."""

from pathlib import Path

from b_application.config.app_config import AppConfig
from d_presentation.dependencies import load_yaml

APPSETTING = Path(__file__).resolve().parents[3] / "config" / "appsetting.yaml"


def shipped_config(project_root: Path = Path(".")) -> AppConfig:
    """
    config/appsetting.yaml, the file load_settings reads, without the prompts of config/instructions.yaml. A settings
    value has no code default, so a test reads it from here and changes what it needs with model_copy(update=...).
    """
    return AppConfig(project_root=project_root, **load_yaml(APPSETTING))
