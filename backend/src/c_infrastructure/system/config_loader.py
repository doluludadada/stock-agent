# backend/src/c_infrastructure/system/config_loader.py

from pathlib import Path

import yaml

from b_application.schemas.config import AppConfig


def load_settings() -> AppConfig:
    project_root = get_project_root()

    config_dict = load_yaml(project_root / "config" / "appsetting.yaml")
    instruction_dict = load_yaml(project_root / "config" / "instructions.yaml")
    strategy_dict = load_yaml(project_root / "config" / "strategies.yaml")

    inject_prompt_settings(config_dict, instruction_dict)
    inject_strategy_settings(config_dict, strategy_dict)

    return AppConfig(project_root=project_root, **config_dict)


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}

    with open(path, encoding="utf-8") as config_file:
        return yaml.safe_load(config_file) or {}


def inject_prompt_settings(config_dict: dict, instruction_dict: dict) -> None:
    if not instruction_dict:
        return

    ai_config = config_dict.setdefault("ai", {})
    ai_config["system_prompt"] = instruction_dict.get("system_prompt")
    ai_config["rag_injection_prompt"] = instruction_dict.get("rag_injection_prompt")

    prompts_config = config_dict.setdefault("prompts", {})
    prompts_config["analysis_report_fundamental"] = instruction_dict.get("ai_analysis_report_prompt_fundamental")
    prompts_config["analysis_report_momentum"] = instruction_dict.get("ai_analysis_report_prompt_momentum")


def inject_strategy_settings(config_dict: dict, strategy_dict: dict) -> None:
    strategies = strategy_dict.get("strategies", {})

    if not strategies:
        return

    active_strategy = config_dict.get("analysis", {}).get("active_strategy", "moderate")

    if active_strategy not in strategies:
        raise ValueError(f"Strategy configuration not found: {active_strategy}")

    config_dict["strategies"] = strategies
    config_dict["strategy"] = strategies[active_strategy]


def get_project_root() -> Path:
    current_path = Path(__file__).resolve()

    for parent in current_path.parents:
        if (parent / "justfile").exists() or (parent / ".git").exists():
            return parent

    raise FileNotFoundError("Could not find project root.")
