from pathlib import Path

import yaml

from b_application.schemas.config import AppConfig


def load_settings() -> AppConfig:
    project_root = get_project_root()

    config_path = project_root / "config" / "appsetting.yaml"
    instruction_path = project_root / "config" / "instructions.yaml"
    strategies_path = project_root / "config" / "strategies.yaml"

    config_dict = {}

    # 1. Load Base App Settings
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config_dict = yaml.safe_load(f) or {}

    # 2. Inject Prompts from instructions.yaml
    if instruction_path.exists():
        with open(instruction_path, "r", encoding="utf-8") as f:
            instruct_data = yaml.safe_load(f) or {}

            ai_config = config_dict.setdefault("ai", {})
            ai_config["system_prompt"] = instruct_data.get("system_prompt")
            ai_config["rag_injection_prompt"] = instruct_data.get("rag_injection_prompt")

            prompts_config = config_dict.setdefault("prompts", {})
            prompts_config["analysis_report_fundamental"] = instruct_data.get("ai_analysis_report_prompt_fundamental")
            prompts_config["analysis_report_momentum"] = instruct_data.get("ai_analysis_report_prompt_momentum")

    # 3. Inject active Strategy from strategies.yaml
    if strategies_path.exists():
        with open(strategies_path, "r", encoding="utf-8") as f:
            strat_yaml = yaml.safe_load(f) or {}

            # Find out which strategy is active (default to 'moderate')
            active_strat = config_dict.get("analysis", {}).get("active_strategy", "moderate")

            # Extract those specific thresholds and inject them
            strategy_data = strat_yaml.get("strategies", {}).get(active_strat, {})
            config_dict["strategy"] = strategy_data

    # Pydantic will now validate everything and apply defaults for missing fields!
    return AppConfig(project_root=project_root, **config_dict)


def get_project_root() -> Path:
    current_path = Path(__file__).resolve()
    for parent in current_path.parents:
        if (parent / "justfile").exists() or (parent / ".git").exists():
            return parent
    raise FileNotFoundError("Could not find project root.")
