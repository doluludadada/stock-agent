"""
How the CLI and the Web API load their settings at startup, and refuse an unsafe trading setup. The administrator's
settings editor validates a candidate file through the same two functions, so a saved file is one the app starts with.
"""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from a_domain.types.enums import ExecutionProvider, OrderMode, SettingsFile, SystemEnvironment
from b_application.config.app_config import AppConfig


def get_project_root() -> Path:
    """The nearest folder above this file that holds the justfile or .git: config/, .env and stock_agent.db live there."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "justfile").exists() or (parent / ".git").exists():
            return parent

    raise FileNotFoundError("Could not find project root.")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    with path.open(encoding="utf-8") as config_file:
        return yaml.safe_load(config_file) or {}


def settings_revision(text: str) -> str:
    """A settings file's revision: the SHA-256 of its UTF-8 text, so any edit, by any editor, changes it."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def settings_text(project_root: Path, file: SettingsFile) -> str:
    path = project_root / "config" / file.file_name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def inject_prompt_settings(settings: dict[str, Any], instructions: dict[str, Any]) -> None:
    """Copies the AI prompts of config/instructions.yaml into the ai and prompts sections of the settings."""
    if not instructions:
        return

    ai_settings = settings.setdefault("ai", {})
    ai_settings["system_prompt"] = instructions.get("system_prompt")
    ai_settings["rag_injection_prompt"] = instructions.get("rag_injection_prompt")

    prompts = settings.setdefault("prompts", {})
    prompts["analysis_report_fundamental"] = instructions.get("ai_analysis_report_prompt_fundamental")
    prompts["analysis_report_momentum"] = instructions.get("ai_analysis_report_prompt_momentum")
    prompts["valuation_explanation"] = instructions.get("ai_valuation_explanation_prompt")
    prompts["social_sentiment"] = instructions.get("social_sentiment_prompt")


def inject_built_in_strategies(settings: dict[str, Any], strategies_folder: Path) -> None:
    """Replaces each id in technical.built_in_strategies with its config/strategies/<id>.json; AppConfig validates them."""
    technical = settings.get("technical", {})
    ids = technical.get("built_in_strategies", [])
    technical["built_in_strategies"] = [
        json.loads((strategies_folder / f"{strategy_id}.json").read_text(encoding="utf-8")) for strategy_id in ids
    ]


def load_settings(candidates: Mapping[SettingsFile, str] | None = None) -> AppConfig:
    """
    config/appsetting.yaml with the prompts of config/instructions.yaml and the built-in strategies of
    config/strategies/. AppConfig reads the secrets from .env and keeps each file's revision, the settings this
    process runs on. A candidate text stands in for its file: the administrator's edit is validated by the same load.
    """
    project_root = get_project_root()
    texts = {file: (candidates or {}).get(file, settings_text(project_root, file)) for file in SettingsFile}
    settings = yaml.safe_load(texts[SettingsFile.APPSETTING]) or {}

    inject_prompt_settings(settings, yaml.safe_load(texts[SettingsFile.INSTRUCTIONS]) or {})
    inject_built_in_strategies(settings, project_root / "config" / "strategies")
    revisions = {file: settings_revision(text) for file, text in texts.items()}

    try:
        return AppConfig(project_root=project_root, settings_revisions=revisions, **settings)
    except ValidationError as error:
        raise InvalidSettingsError(error) from None


class InvalidSettingsError(RuntimeError):
    """
    config/ or .env hold a value the settings refuse, so the CLI or the Web API does not start. Each problem is a
    location and pydantic's message, never the value: pydantic's own text shows the input, which can be a secret
    from .env, so neither the message nor a traceback carries the ValidationError.
    """

    def __init__(self, error: ValidationError) -> None:
        self.problems = [f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}" for problem in error.errors()]
        super().__init__("\n".join(["The settings in config/ and .env do not validate:", *(f"  - {line}" for line in self.problems)]))


class TradingSetupError(RuntimeError):
    """The trading settings or the broker login do not let the CLI or the Web API start. The message says what to change."""


def validate_trading_environment(config: AppConfig) -> None:
    """
    Refuses a trading setup that could send an order nobody meant to send, before any broker is contacted.

    - DEV uses the mock broker only.
    - mock_only order mode needs the mock broker.
    - live order mode needs environment live and the Shioaji broker.
    - The Shioaji broker needs its credentials.
    Order mode disabled never orders, so outside DEV it may read a real Shioaji account.
    """
    environment, provider, mode = config.environment, config.trading.execution_provider, config.trading.order_mode

    if environment == SystemEnvironment.DEV and provider != ExecutionProvider.MOCK:
        raise TradingSetupError("DEV environment requires MockExecutionProvider")

    if mode == OrderMode.MOCK_ONLY and provider != ExecutionProvider.MOCK:
        raise TradingSetupError(
            f"order_mode mock_only needs execution_provider mock, not {provider.value}. "
            f"Use order_mode disabled to read the {provider.value} account without ordering"
        )

    if mode == OrderMode.LIVE and (environment != SystemEnvironment.LIVE or provider != ExecutionProvider.SHIOAJI):
        raise TradingSetupError(
            f"order_mode live needs environment live and execution_provider shioaji, not {environment.value} and {provider.value}"
        )

    if provider == ExecutionProvider.SHIOAJI and (missing := config.shioaji.missing_credentials()):
        raise TradingSetupError(f"execution_provider shioaji needs {', '.join(missing)} in the environment or .env")
